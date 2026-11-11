# Dead Code Detection Protocol (Phases 0–2)

Canonical, **read-only** detection protocol for `dead-code-hunter`. Two callers use it:

- The `dead-code-hunter` **skill**, when it runs detection inline.
- The `dead-code-hunter` **subagent** (Claude Code / OpenCode), when the skill delegates detection to keep the main context clean.

Both must produce the same **Detection Report** (see the end of this file) so the skill can build the removal plan from either one.

> This protocol never edits, writes, deletes, installs, or commits. If you are tempted to fix something, record it in the report instead.

## Scope: what counts as dead code

- Files not imported from any live entry point.
- Named exports that no one consumes (`export function foo` not appearing in any `import`).
- Private functions, classes, variables, and types never used inside their own module.
- Unused imports.
- Dependencies declared in `package.json` that no file imports (`dependencies` and `devDependencies`).
- Unreachable code branches (`if (false)`, code after `return`, dead flags).
- React components never rendered, hooks never consumed, routes declared without links.
- Tests for files that no longer exist.
- Orphan assets / CSS classes / i18n keys *(only if the user explicitly asked — high false positive rate)*.

## Signals that are NOT dead code

Rule these out before classifying anything as dead:

- Project entry points: `main` / `module` / `bin` / `exports` in `package.json`, files in `pages/`, `app/`, `api/`, `routes/`, and config files (`*.config.*`, `next.config.*`, `vite.config.*`, `tailwind.config.*`, `postcss.config.*`, `eslint.config.*`, `vitest.config.*`, `jest.config.*`).
- Side effects: files imported only for their side effect (`import './polyfill'`), or listed in the `sideEffects` field of `package.json`.
- Public API of a library: anything re-exported from the root `index.ts` or listed in `exports` of `package.json` is live even with zero internal consumers.
- Dynamic usage: `require(variable)`, `` import(`./locales/${lang}`) ``, string lookups (`registry["X"]`), decorators, JSX by name, routes declared as strings.
- Reflection / dependency injection (NestJS, InversifyJS, etc.).
- Types consumed only from ambient `.d.ts` files or JSDoc.
- Tests, fixtures, mocks, Storybook stories, MDX.
- Code behind feature flags toggleable at runtime.
- Dependencies used only by tooling: CLI binaries invoked from `scripts`, ESLint/Babel/PostCSS plugins referenced by name in config files, `@types/*` packages.

## Phase 0 — Recon

1. Read the root `package.json` and, if present, workspace manifests (`workspaces`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`) and each workspace `package.json`.
2. Identify: package manager (pnpm / yarn / npm / bun), project type (Node lib, Next app, Vite app, monorepo, CLI), TypeScript version, test framework.
3. List the real entry points (`main`, `module`, `exports`, `bin`, `scripts`, files in `app/`, `pages/`, `src/index.*`).
4. Check repo state: `git status --short` and `git rev-parse --abbrev-ref HEAD`. **Record** whether the tree is dirty. Do not stash, commit, or clean anything — the caller decides what to do with a dirty tree.
5. Measure size: `git ls-files '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs' | wc -l`. If it is >500 files and no subdirectory scope was given, flag it in the report so the caller can suggest narrowing scope. Keep going unless told otherwise.
6. **Baseline:** identify the commands the project uses to verify itself (`tsc --noEmit`, `test`, `build`, `lint` scripts). Run them **only** if the caller explicitly authorized it; otherwise list them under `baseline.commands` with status `not-run`.

## Phase 1 — Static analysis

Combine several sources; never trust a single tool.

**Tool availability first.** Only run analyzers that are already available locally — check `node_modules/.bin`, the project's `devDependencies`, or use `npx --no-install <tool>` / `pnpm exec <tool>` / `yarn exec <tool>`. **Never** let a bare `npx <tool>` trigger an *"Ok to proceed?"* install prompt — in a non-interactive shell it hangs or fails, and installing is forbidden. If a tool is missing, record it under `tools.missing` and continue with what exists.

1. **Knip** (preferred — files + exports + deps in one run):
   ```bash
   npx --no-install knip --reporter json
   ```
   If there is no knip config and the output is noisy, note in the report that a minimal `knip.json` would help. Do not create it.
2. **ts-prune** as a second opinion on exports:
   ```bash
   npx --no-install ts-prune
   ```
3. **depcheck** for dependencies:
   ```bash
   npx --no-install depcheck --json
   ```
4. **Reference search** for each candidate, to rule out dynamic use. Use `git grep` or `rg` — **not** bare `grep -r`. They respect `.gitignore` and skip `node_modules`, `dist`, `build`, `.next`, `coverage`; searching those produces false "it's used" hits. Search the identifier as a plain string, not only as an import:
   ```bash
   git grep -n "functionName"
   ```
5. **LSP / find-references**, if your environment exposes one (e.g. an `lsp` tool): use it to confirm a symbol has zero references. Treat it as one more signal, not a replacement for the others.
6. **Aliases and barrels.** Before calling a file orphaned:
   - Resolve tsconfig `paths` / `baseUrl` aliases (`@/utils/x`) — a search for `from './utils/x'` misses the aliased form.
   - Check barrel re-exports (`index.ts` doing `export * from './x'`) — consumers may import through the barrel.

Large outputs: keep raw tool output out of the final report. Summarize counts and keep only the candidates with their evidence.

## Phase 2 — Classification

Assign every candidate one confidence level:

| Level | Meaning | Rule |
|-------|---------|------|
| 🟢 `high` | Safe to propose removal | No references, outside entry points, no detectable dynamic use, confirmed by **≥2 independent signals** |
| 🟡 `medium` | Propose with caution | Only one signal, or matches a pattern that *could* be dynamic use |
| 🔴 `suspicious` | Do **not** propose removal | Tool flags it but there are hints of dynamic use, it sits near configs, or it is a public/root export — list for human review only |

Also assign each candidate a **kind**, which drives batching later:
`unused-import` · `unused-export` · `unused-local` · `orphan-file` · `unused-dependency` · `unreachable-code` · `orphan-test` · `other`.

## Detection Report (output contract)

End detection with exactly this structure. The skill builds the removal plan from it, so be precise and keep it compact (no raw tool dumps).

```markdown
## Detection Report — dead-code-hunter

**Project:** <type>, <package manager>, TS <version>, tests: <framework>
**Scope:** <repo root | subdirectory> · <N> source files<, ⚠ large repo — suggest narrowing>
**Git:** branch `<name>`, tree <clean | DIRTY: N files>
**Entry points:** <comma-separated list>
**Tools:** ran <knip, ts-prune, ...> · missing <...> · coverage <full | reduced — grep only>
**Baseline:** <command → pass | fail (summary) | not-run>, ...

### Candidates

| # | Confidence | Kind | Location | What | Evidence |
|---|-----------|------|----------|------|----------|
| 1 | high | unused-import | src/foo.ts:3 | `bar`, `baz` | knip + git grep: 0 refs |
| 2 | medium | unused-export | src/utils/format.ts:12 | `formatLegacy` | ts-prune only |
| 3 | suspicious | orphan-file | src/plugins/registry.ts | whole file | dynamic lookup at src/loader.ts:42 |

### Notes
- <false-positive risks, config suggestions (e.g. knip.json), anything the caller must know>
```

Rules for the table:
- One row per removable unit (group several imports from the same line/file into one row).
- `Location` uses `path:line` when a line exists, so it is clickable.
- `Evidence` names the signals actually used. A `high` row must list at least two.
