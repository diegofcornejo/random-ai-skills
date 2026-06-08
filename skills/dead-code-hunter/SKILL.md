---
name: dead-code-hunter
description: Use when finding or removing dead code in JS/TS projects (Node, React, monorepos) — orphan files, unused exports, unreferenced imports, unused dependencies, unreachable branches. Triggers when the user mentions "dead code", "unused code", "orphan exports/files", "cleanup imports", "unused dependencies", "reduce bundle size", or asks to find code that nothing references.
---

# Dead Code Hunter

Detect and remove **dead code** in JavaScript / TypeScript projects (Node, React, monorepos). The goal is a rigorous diagnosis, a clear action plan, and — once approved — safe step-by-step execution.

## Principles

1. **Evidence over intuition.** Never mark something as dead without confirming it with at least two signals (e.g. tool + manual grep, or import analysis + reference search).
2. **False positives are the main enemy.** Deleting something live is far worse than leaving something dead. When in doubt, mark as "suspicious" rather than "dead".
3. **Deletion is the last phase.** First detect, then propose, then confirm, then execute in small reversible batches.
4. **Nothing destructive happens without user approval.** Present the plan and wait for the user to approve it before any edits, writes, or deletions.

## Scope: what counts as dead code

- Files not imported from any live entry point.
- Named exports that no one consumes (`export function foo` not appearing in any `import`).
- Private functions, classes, variables, and types never used inside their own module.
- Unused imports.
- Dependencies declared in `package.json` that no file imports (`dependencies` and `devDependencies`).
- Unreachable code branches (`if (false)`, code after `return`, dead flags).
- React components never rendered, hooks never consumed, routes declared without links.
- Tests for files that no longer exist.
- Orphan assets / CSS classes / i18n keys *(only if the user explicitly asks — high false positive rate)*.

## Signals that are NOT dead code

Before proposing deletion, rule out these cases:

- Project entry points: `main` / `bin` / `exports` in `package.json`, files in `pages/`, `app/`, `api/`, `routes/`, files like `*.config.*`, `next.config.*`, `vite.config.*`, `tailwind.config.*`, `postcss.config.*`, `eslint.config.*`, `vitest.config.*`, `jest.config.*`.
- Side effects: files imported only for their side effect (`import './polyfill'`), declared in the `sideEffects` field of `package.json`.
- Public API of a library: any export re-exported from the root `index.ts` or listed in the `exports` field of `package.json` is considered live even with no internal consumption.
- Dynamic usage: `require(variable)`, `` import(`./locales/${lang}`) ``, string lookups (`registry["X"]`), decorators, JSX by name, routes declared as strings.
- Reflection / dependency injection (NestJS, InversifyJS, etc.).
- Types consumed only from ambient `.d.ts` files or JSDoc.
- Tests, fixtures, mocks, Storybook, MDX.
- Code behind feature flags toggleable at runtime.

## Workflow

**Always** follow this order. Do not skip phases.

### Phase 0 — Recon (no questions yet)

1. Read the root `package.json` and, if present, the workspace `package.json` files (`workspaces`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`).
2. Identify: package manager (pnpm/yarn/npm), project type (Node lib, Next app, Vite app, monorepo, CLI), TS version, test framework.
3. List the actual entry points (`main`, `module`, `exports`, `bin`, `scripts` fields, files in `app/`, `pages/`, `src/index.*`).
4. Verify repo state with `git status` and `git rev-parse --abbrev-ref HEAD`. If there are uncommitted changes, **stop** and ask the user to commit or stash before continuing — this is critical for being able to revert.
5. Establish a **green baseline**: run the type check / tests / build the project already uses (`tsc --noEmit`, `npm test` / `pnpm test`, build) to confirm they pass *before* any deletion. If the baseline is already red, record the known failures — otherwise you cannot tell what your deletions broke. Ask the user before running anything slow or unfamiliar.

### Phase 1 — Static analysis

Combine multiple sources; do not trust a single tool.

**Tool availability first.** Only run analyzers that are already available locally — check `node_modules/.bin`, the project's `devDependencies`, or use `npx --no-install <tool>` / `pnpm exec <tool>`. **Never** let a bare `npx <tool>` trigger an interactive *"Ok to proceed?"* install prompt — in a non-interactive shell it hangs or fails, and installing is forbidden without explicit permission (see Golden rules). If a tool is missing, report it and work with what's there. If only grep is available, say so clearly and warn that coverage will be lower.

1. **Knip** (preferred, covers files + exports + deps in a single run):
   ```
   npx --no-install knip --reporter json
   ```
   If the project has no knip config, first run with defaults; if there's too much noise, suggest creating a minimal `knip.json`.
2. **ts-prune** as a second opinion on exports:
   ```
   npx --no-install ts-prune
   ```
3. **depcheck** for dependencies:
   ```
   npx --no-install depcheck --json
   ```
4. **Manual search** on suspicious names to rule out dynamic uses. Use `git grep` or `rg` (ripgrep), **not** bare `grep -r` — they respect `.gitignore` and skip `node_modules`, `dist`, `build`, `.next`, `coverage` by default. Searching those dirs produces false "it's used" hits that hide real dead code. Search for the identifier as a plain string, not just as an import:
   ```
   git grep -n "functionName"
   ```
5. Before confirming a file is orphaned, account for **path aliases and barrel files**, or you will flag live code as dead:
   - Resolve tsconfig `paths` / `baseUrl` aliases (`@/utils/x`) — a search for `from './utils/x'` misses the aliased form.
   - Check barrel re-exports (an `index.ts` doing `export * from './x'`) — consumers may import through the barrel, not the file directly.

### Phase 2 — Classification

Group findings into three confidence levels:

- **🟢 High confidence** — file or export with no references, outside entry points, no detectable dynamic use, confirmed by at least two signals.
- **🟡 Medium confidence** — only one signal, or matches a pattern that could be dynamic use.
- **🔴 Low confidence / suspicious** — tool flags it but there are hints of dynamic use, it's near configs, or it's a root export. **Do not propose deletion**, just list it for human review.

### Phase 3 — Plan

Present the user with a structured plan **before touching anything**. Format:

```
## Dead code removal plan

Summary: N files, M exports, K dependencies.

### Batch 1 — Unused imports (risk: low)
- src/foo.ts: remove imports `bar`, `baz`
- src/qux.tsx: remove import `unused`

### Batch 2 — Orphan exports (risk: low-medium)
- src/utils/format.ts: drop `export` from `formatLegacy` (function becomes private)
- src/utils/format.ts: remove function `oldHelper` (no references)

### Batch 3 — Whole files (risk: medium)
- src/legacy/parser.ts (12 lines, no incoming imports)
- src/components/OldButton.tsx (unused for N commits)

### Batch 4 — Dependencies (risk: medium-high)
- Remove from package.json: `lodash.merge`, `moment`

### Will NOT be touched (suspicious, requires your judgment):
- src/plugins/registry.ts: marked as dead but there's a dynamic lookup at src/loader.ts:42
- ...
```

End the plan with: *"Do you approve this plan? You can tell me: 'all', 'only batches 1 and 2', 'batch 1', 'cancel', or request adjustments."*

**Stop and wait for the response.** Do not start editing.

### Phase 4 — Execution

Once the user approves:

1. Execute **one batch at a time**, in order of lowest to highest risk.
2. Before each batch, verify the working tree is clean (`git status`). If there are uncommitted changes from a previous batch, remind the user to commit them first.
3. After each batch, suggest running verification: `tsc --noEmit`, `eslint`, the tests (`npm test` / `pnpm test`), and a build if applicable. Ask the user whether to run them, or whether they prefer to run them manually. Compare results against the Phase 0 baseline.
4. If a verification fails, **stop**. Report exactly what broke and propose reverting that batch (`git restore`/`git checkout`) before continuing.
5. Once a batch passes verification, **commit it** before starting the next (e.g. `chore: remove unused imports (batch 1)`). The commit is the actual revert point — one batch per commit keeps the next batch's failures attributable and easy to roll back.

### Phase 5 — Wrap-up

When done, deliver a summary:

- Files removed, lines deleted, dependencies dropped.
- Approximate bundle reduction if measurable.
- List of "suspicious" items left untouched, for later human review.
- Suggested commit message (e.g. `chore: remove dead code (batches 1-3)`).

## Golden rules

- **Never** run `rm -rf` on directories without explicit, narrow paths confirmed by the user.
- **Never** run `git reset --hard`, `git clean`, or `git push`.
- **Never** install new packages without explicit permission.
- **Never** modify `package.json` and code files in the same batch — always separate dependency changes from code changes.
- If you find secrets, credentials, or `.env*` files in your way, ignore them and do not read beyond their existence.
- If the project has >500 files, suggest narrowing the scope to a subdirectory before starting.
- If the repo is dirty at the start, do not proceed. It's the only way to guarantee revertibility.
