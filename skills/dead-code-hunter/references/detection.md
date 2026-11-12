# Dead Code Detection Protocol (Phases 0–2)

Canonical, **read-only** detection protocol for `dead-code-hunter`. Two callers use it:

- The `dead-code-hunter` **skill**, when it runs detection inline.
- The `dead-code-hunter` **subagent** (Claude Code / OpenCode), when the skill delegates detection to keep the main context clean.

Both must produce the same **Detection Report** (see the end of this file) so the skill can build the removal plan from either one.

> This protocol never edits, writes, deletes, installs, or commits inside the project. The only files it creates are analyzer outputs in a temp directory **outside** the project. If you are tempted to fix something, record it in the report instead.

**Paths.** `<skill-dir>` is the folder that contains this file's parent `references/` folder (i.e. the `dead-code-hunter` skill directory). Run every command with the **project root** as the working directory and call scripts by absolute path: `python3 <skill-dir>/scripts/merge-signals.py …`.

## Scope: what counts as dead code

- Files not imported from any live entry point.
- Named exports, exported types, and enum / namespace members that no one consumes.
- Private functions, classes, variables, and types never used inside their own module.
- Unused imports.
- Dependencies declared in `package.json` that no file, config, or script uses (`dependencies` and `devDependencies`).
- Unreachable code (code after `return` / `throw`, unused labels) and dead flags (`if (false)`).
- React components never rendered, hooks never consumed, routes declared without links.
- Code used **only by tests** (alive in the default run, dead in production mode).
- Tests for files that no longer exist.
- Orphan assets / CSS classes / i18n keys *(only if the user explicitly asked — high false-positive rate)*.

Out of scope on purpose: **unused function parameters** (callback signatures such as `(req, res, next)` make them mostly noise).

## Signals that are NOT dead code

Rule these out before classifying anything as dead:

- Project entry points: `main` / `module` / `bin` / `exports` in `package.json`, files in `pages/`, `app/`, `api/`, `routes/`, and config files (`*.config.*`, `next.config.*`, `vite.config.*`, `tailwind.config.*`, `postcss.config.*`, `eslint.config.*`, `vitest.config.*`, `jest.config.*`).
- Side effects: files imported only for their side effect (`import './polyfill'`), or listed in the `sideEffects` field of `package.json`.
- Public API of a library: anything re-exported from the root `index.ts` or listed in `exports` of `package.json` is live even with zero internal consumers.
- Dynamic usage: `require(variable)`, `` import(`./locales/${lang}`) ``, string lookups (`registry["X"]`), decorators, JSX by name, routes declared as strings, file-system routing and glob imports (`import.meta.glob`, `require.context`).
- Reflection / dependency injection (NestJS, InversifyJS, etc.).
- Types consumed only from ambient `.d.ts` files or JSDoc.
- Tests, fixtures, mocks, Storybook stories, MDX.
- Code behind feature flags toggleable at runtime.
- Dependencies used only by tooling: CLI binaries invoked from `scripts`, ESLint/Babel/PostCSS plugins referenced by name in config files, `@types/*` packages, peer dependencies required by another package.

## Phase 0 — Recon

1. Read the root `package.json` and, if present, workspace manifests (`workspaces`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`) and each workspace `package.json`.
2. Identify: package manager (lockfile: `pnpm-lock.yaml`, `yarn.lock` + `.yarnrc.yml` → Yarn Berry, `.pnp.cjs` → Yarn PnP, `bun.lock[b]`, `package-lock.json`), project type (Node lib, Next app, Vite app, monorepo, CLI), TypeScript version, test framework, `node --version`.
3. List the real entry points (`main`, `module`, `exports`, `bin`, `scripts`, files in `app/`, `pages/`, `src/index.*`).
4. Check repo state: `git status --short` and `git rev-parse --abbrev-ref HEAD`. **Record** whether the tree is dirty. Do not stash, commit, or clean anything — the caller decides.
5. Measure size: `git ls-files '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs' '*.mts' '*.cts' | wc -l`. If it is >500 files and no subdirectory scope was given, flag it so the caller can suggest narrowing scope. Keep going unless told otherwise.
6. **Dependencies installed?** Check that `node_modules/` exists (or `.pnp.cjs` for Yarn PnP). Without it knip cannot load framework configs (exit code 2 or a flood of `unlisted` issues) and `tsc` cannot resolve types. **Do not install.** Record `coverage: reduced — dependencies not installed` and continue with what works.
7. **Knip config:** look for `knip.json`, `knip.jsonc`, `.knip.json`, `.knip.jsonc`, `knip.ts`, `knip.config.ts`, or a `knip` key in `package.json`. Record whether one exists.
8. **Baseline:** identify the verification commands (`tsc --noEmit`, `test`, `build`, `lint` scripts). Run them **only** if the caller explicitly authorized it; otherwise list them under **Baseline** as `not-run`.

## Phase 1 — Static analysis

Combine several independent sources; never trust a single tool.

| Signal | Tool | Finds | Notes |
|--------|------|-------|-------|
| Module graph | **knip** (current major: 6; needs Node `^20.19 \|\| >=22.12`, else use `knip@5`) | orphan files, unused exports / types / enum & namespace members, unused & unlisted dependencies | Primary tool. Replaces ts-prune and depcheck. |
| Compiler | **tsc** (the project's own TypeScript) | unused imports and locals, unreachable code | Present in almost every TS project; no install needed. |
| Text search | **git grep** (via `merge-signals.py --grep`) | any remaining mention: dynamic use, configs, strings | Respects `.gitignore`; the script also skips `dist/`, `build/`, `.next/`, `coverage/`, `node_modules/`. |
| References | **LSP** find-references, if your environment exposes one | zero-reference confirmation | Optional extra signal. |
| Linter | project's ESLint / Biome / oxlint, only if already configured with unused-vars rules | unused imports / vars | Optional. Run **without** `--fix`; inspect the `lint` script first, some include `--fix`. |
| Legacy | ts-prune, depcheck | exports / deps | **Archived** upstream. Use only if knip cannot run *and* they are already installed. Same signal family as knip, not an independent one. |

### 1.1 Resolve the analyzers (no installs)

**knip**, first match wins:

1. Local binary: `node_modules/.bin/knip` exists → run it directly (works for npm, pnpm, Yarn classic, bun). Yarn PnP: `yarn knip`.
2. **Ephemeral run**, only if the caller authorized it (`Ephemeral analyzers: authorized`): `npx -y knip@6` (npm / Yarn / bun) or `pnpm dlx knip@6`. It runs from the package-manager cache and does **not** touch `package.json`, the lockfile, or `node_modules`. It still needs the project's own dependencies installed (Phase 0, step 6).
3. Otherwise record `knip` under **missing** and suggest the ephemeral run in **Notes**.

Never run a bare `npx knip`: without `-y` or `--no` it may hang on an *"Ok to proceed?"* prompt in a non-interactive shell.

**tsc**: `node_modules/.bin/tsc` (Yarn PnP: `yarn tsc`). Never fall back to a global or ephemeral TypeScript — a different version gives different diagnostics.

### 1.2 Run them

Write outputs to a temp directory **outside** the project. Never redirect to `knip.json` inside the project: that is knip's own config filename and breaks the next run.

`<knip>` below is the literal command from 1.1 (e.g. `node_modules/.bin/knip` or `npx -y knip@6`). Write it out in each command; don't store a multi-word command in a shell variable (zsh doesn't word-split it). If each shell call starts fresh, print `$OUT` once and reuse the literal path.

```bash
OUT="$(mktemp -d)"; echo "$OUT"

# Default run: everything, including tests and tooling.
<knip> --reporter json --no-progress --no-exit-code > "$OUT/knip.json" 2> "$OUT/knip.err"
# Production run: only shipped code. Dead here but alive above = used only by tests.
<knip> --production --reporter json --no-progress --no-exit-code > "$OUT/knip-prod.json" 2> "$OUT/knip-prod.err"

# Compiler diagnostics. The extra flags keep it from writing .tsbuildinfo or failing on composite projects.
node_modules/.bin/tsc -p tsconfig.json --noEmit --pretty false \
  --noUnusedLocals --allowUnreachableCode false \
  --composite false --incremental false --declaration false --declarationMap false --emitDeclarationOnly false \
  > "$OUT/tsc.txt" 2>&1

# Merge, de-duplicate, and attach git-grep references for each candidate.
python3 <skill-dir>/scripts/merge-signals.py \
  --knip "$OUT/knip.json" --knip-prod "$OUT/knip-prod.json" --tsc "$OUT/tsc.txt" \
  --grep [--scope <subdir>]
```

Details:

- **Exit codes.** With `--no-exit-code`, knip exits `0` even when it finds issues. Exit `2` means bad input or a config that failed to load: read `knip.err`, record the reason in **Notes** (usually missing `node_modules` or a broken framework config), and continue without knip.
- **tsc exits non-zero by design** here: the unused-code flags turn findings into errors. Pre-existing type errors are ignored by the script, which keeps only codes TS6133, TS6138, TS6192, TS6196, TS6198, TS6199, TS6205, TS7027, TS7028.
- **Solution-style tsconfig** (`"files": []` + `references`) checks nothing at the root: run `tsc -p` once per referenced `tsconfig.json` and pass each output with its own `--tsc`.
- **Monorepos.** knip understands workspaces natively; to scope to some, add `--workspace <name|dir>`. For a plain subdirectory scope, run on the whole repo and filter with `merge-signals.py --scope <subdir>` (repeatable).
- **Big repos.** Add `--cache` to <knip> (cache lives under `node_modules/.cache`, which is ignored). `merge-signals.py --max N` caps the list (default 300) while keeping exact counts.
- **Fallback without knip:** run tsc + `merge-signals.py --tsc … --grep`, then search orphan-file candidates manually with `git grep`. Mark coverage `reduced`.

### 1.3 What `merge-signals.py` returns

JSON on stdout: `summary` (counts by kind), `candidates`, and `notes`. Each candidate has `id`, `kind`, `file`, `line`, `name`, `signals` (e.g. `["knip", "knip:production"]`, `["tsc:TS6133"]`), and with `--grep` also `refs` (mentions outside the defining module — inside it for locals/imports) plus up to three `ref_samples`. `test_only: true` marks code that only the production run flags, or whose every reference is in a test file. `notes` groups knip's non-dead-code issues (`unlisted`, `binaries`, `unresolved`, `duplicates`), which explain false positives.

### 1.4 Confirm doubtful candidates

- Read each `ref_samples` hit: a string lookup, a route table, or a config entry means dynamic use; the same word in an unrelated identifier or a comment does not.
- **Aliases and barrels.** Before calling a file orphaned, resolve tsconfig `paths` / `baseUrl` aliases (`@/utils/x`) and check barrel re-exports (`export * from './x'`).
- **knip trace:** `<knip> --trace-export <name> --trace-file <file>` or `<knip> --trace-dependency <pkg>` shows where knip thinks something is imported (`(no imports found) ✗` when nothing does).
- **LSP** find-references, if available.

Keep raw tool output out of the report: summarize counts and keep only candidates with their evidence.

## Phase 2 — Classification

**Independent signal families:** knip (default and production runs together count as **one**), tsc, git grep with `refs: 0`, LSP, linter. Legacy tools belong to the knip family.

| Level | Meaning | Rule |
|-------|---------|------|
| 🟢 `high` | Safe to propose removal | ≥2 independent signals (e.g. `knip` + `refs: 0`, or `tsc` + `refs: 0`), outside entry points, no sign of dynamic use |
| 🟡 `medium` | Propose with caution | One signal only, `test_only`, `orphan-test`, or a pattern that *could* be dynamic use |
| 🔴 `suspicious` | Do **not** propose removal | `refs > 0` with a dynamic-looking hit, near configs, public/root export, or in an area where knip notes show `unlisted` / `unresolved` issues (its config is incomplete there) |

Extra rules:

- `unused-import` and `unreachable-code` from tsc plus `refs: 0` are `high`: the compiler is authoritative inside a module.
- `test_only` code stays `medium` at most and goes to the plan with its tests as one unit (delete both, or keep both).
- **Broken test discovery.** If knip's `binaries` / `unlisted` notes include the test runner (vitest, jest, mocha, playwright…) or test files show up as `orphan-file` / `orphan-test`, knip has no runner plugin and is treating tests as orphans. Then `orphan-test` rows are `suspicious`, and the production run cannot reveal test-only code (both runs agree). Say so in **Notes**.
- `unused-dependency` with `refs > 0` (config file, script, plugin name) is `suspicious`.
- Many `unlisted` / `binaries` notes, or no knip config in a framework project, mean knip is missing a plugin or entry: say so, and suggest a minimal `knip.json` in **Notes**. Do not create it.

**Kinds** drive batching later (knip reports a whole unused enum or interface under `types` → `unused-type`; `unused-member` is for individual enum / namespace members):
`unused-import` · `unused-local` · `unreachable-code` · `unused-export` · `unused-type` · `unused-member` · `orphan-file` · `orphan-test` · `unused-dependency` · `unused-catalog-entry` · `other`.

## Detection Report (output contract)

End detection with exactly this structure. The skill builds the removal plan from it, so be precise and keep it compact (no raw tool dumps).

```markdown
## Detection Report — dead-code-hunter

**Project:** <type>, <package manager>, TS <version>, Node <version>, tests: <framework>
**Scope:** <repo root | subdirectory> · <N> source files<, ⚠ large repo — suggest narrowing>
**Git:** branch `<name>`, tree <clean | DIRTY: N files>
**Entry points:** <comma-separated list>
**Tools:** ran <knip 6.x (local | ephemeral), tsc 5.x, git grep, ...> · missing <...> · coverage <full | reduced — reason>
**Knip config:** <path | none>
**Baseline:** <command → pass | fail (summary) | not-run>, ...

### Candidates

| # | Confidence | Kind | Location | What | Evidence |
|---|-----------|------|----------|------|----------|
| 1 | high | unused-import | src/foo.ts:3 | `bar`, `baz` | tsc TS6133 + grep: 0 refs |
| 2 | high | orphan-file | src/legacy/parser.ts | whole file | knip + grep: 0 refs |
| 3 | medium | unused-export | src/utils/format.ts:12 | `formatLegacy` | knip production only (test-only: test/format.test.ts:4) |
| 4 | suspicious | orphan-file | src/plugins/registry.ts | whole file | knip, but dynamic lookup at src/loader.ts:42 |

### Notes
- <false-positive risks, knip config suggestions, tools that failed and why, anything the caller must know>
- <cascades: things that will become dead once a row is removed (e.g. an export whose only consumer is an unused import) — flag them for the next round, don't add rows for them>
```

Rules for the table:
- One row per removable unit (group several imports from the same line/file into one row).
- `Location` uses `path:line` when a line exists, so it is clickable.
- `Evidence` names the signals actually used. A `high` row must list at least two independent ones.
