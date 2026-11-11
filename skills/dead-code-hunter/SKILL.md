---
name: dead-code-hunter
description: Use when finding or removing dead code in JS/TS projects (Node, React, monorepos) — orphan files, unused exports, unreferenced imports, unused dependencies, unreachable branches. Triggers when the user mentions "dead code", "unused code", "orphan exports/files", "cleanup imports", "unused dependencies", "knip", "ts-prune", "depcheck", "reduce bundle size", or asks to find code that nothing references.
---

# Dead Code Hunter

Detect and safely remove **dead code** in JavaScript / TypeScript projects (Node, React, monorepos). You produce a rigorous diagnosis, a risk-ordered plan, and — only after approval — execute it in small, reversible batches.

This skill is the **orchestrator**. It owns the conversation with the user (plan, approval, execution). The read-only detection work can be done inline or delegated to the `dead-code-hunter` subagent.

## Principles

1. **Evidence over intuition.** Never mark something as dead without at least two independent signals (e.g. knip + `git grep`, or import analysis + LSP references).
2. **False positives are the main enemy.** Deleting something live is far worse than leaving something dead. When in doubt, mark it `suspicious`.
3. **Deletion is the last phase.** Detect → propose → confirm → execute in small reversible batches.
4. **Nothing destructive happens without user approval.** Present the plan and wait before any edit, write, or deletion.

## Workflow

Always follow this order. Do not skip phases.

### Step 1 — Preconditions (main thread)

1. Run `git status --short`. If the tree is dirty, **stop** and ask the user to commit or stash first — a clean tree is the only way to guarantee revertibility.
2. Ask (or infer from the request) the **scope**: whole repo or a subdirectory.
3. Ask whether you may run the project's verification commands (type check / tests / build) to record a baseline. Default: ask before anything slow.

### Step 2 — Detection (Phases 0–2): delegate or inline

The full protocol, the "is NOT dead code" checklist, and the **Detection Report** format live in [references/detection.md](references/detection.md).

**Delegate when a `dead-code-hunter` subagent is available** — it keeps knip/ts-prune/grep output out of the main context:

| Environment | How to delegate |
|-------------|-----------------|
| Claude Code | `Agent` tool with `subagent_type` `dead-code-hunter` (plugin install: `dead-code-hunter:dead-code-hunter`) |
| OpenCode | Ask the `dead-code-hunter` subagent via the subagent tool (or `@dead-code-hunter`) |
| Anything else / no subagent | Run detection **inline**: read `references/detection.md` and follow Phases 0–2 yourself |

Delegation prompt — fill in the placeholders, and pass the **absolute path** of `references/detection.md` (this skill's base directory + `references/detection.md`):

```text
Run the dead-code detection protocol (Phases 0–2) and return ONLY the Detection Report.
Protocol file: <absolute path to references/detection.md>
Project root: <absolute path>
Scope: <repo root | subdirectory>
Baseline commands: <authorized: run them | NOT authorized: list only>
Extra context from the user: <anything relevant, e.g. "public library", "ignore storybook">
Read-only: do not edit, write, delete, install, or commit anything.
```

The subagent returns a **Detection Report**. Treat it as evidence, not as truth: spot-check at least the `high` rows you will act on (one `git grep` each is enough) before putting them in the plan.

### Step 3 — Plan (main thread)

Build the plan from the Detection Report. Only `high` and `medium` rows become actions; `suspicious` rows go to "Will NOT be touched". Batch by kind, lowest risk first, and **never** mix `package.json` changes with code changes in the same batch.

```markdown
## Dead code removal plan

Summary: N files, M exports, K dependencies. Tools: <ran> · coverage: <full | reduced>.

### Batch 1 — Unused imports (risk: low)
- src/foo.ts:3 — remove imports `bar`, `baz`

### Batch 2 — Orphan exports (risk: low-medium)
- src/utils/format.ts:12 — drop `export` from `formatLegacy` (becomes private)
- src/utils/format.ts:40 — remove function `oldHelper` (no references)

### Batch 3 — Whole files (risk: medium)
- src/legacy/parser.ts (12 lines, no incoming imports)

### Batch 4 — Dependencies (risk: medium-high)
- Remove from package.json: `lodash.merge`, `moment`

### Will NOT be touched (suspicious — needs your judgment)
- src/plugins/registry.ts — flagged, but dynamic lookup at src/loader.ts:42
```

End with: *"Do you approve this plan? You can say: 'all', 'only batches 1 and 2', 'batch 1', 'cancel', or request adjustments."*

**Stop and wait for the response.** Do not start editing.

### Step 4 — Execution (main thread)

Execution stays in the main conversation so the user can see and approve each batch.

1. Execute **one batch at a time**, lowest risk first.
2. Before each batch, confirm the tree is clean (`git status --short`). If the previous batch is uncommitted, ask the user to commit it (or offer to).
3. After each batch, run (or ask the user to run) the verification commands — `tsc --noEmit`, lint, tests, build — and compare with the baseline.
4. If verification fails, **stop**. Report exactly what broke and propose reverting that batch (`git restore <files>`) before continuing.
5. Once a batch passes, commit it before the next one (e.g. `chore: remove unused imports (batch 1)`). One batch per commit keeps failures attributable and rollbacks trivial.

### Step 5 — Wrap-up

- Files removed, lines deleted, dependencies dropped.
- Approximate bundle reduction, if measurable.
- `suspicious` items left untouched, for later human review.
- Suggested follow-ups (e.g. add `knip` to CI, create a `knip.json`).

## Golden rules

- **Never** run `rm -rf` on directories without explicit, narrow paths confirmed by the user.
- **Never** run `git reset --hard`, `git clean`, `git push`, or force operations.
- **Never** install new packages without explicit permission.
- **Never** modify `package.json` and code files in the same batch.
- If you meet secrets, credentials, or `.env*` files, ignore them and do not read past their existence.
- If the project has >500 source files, suggest narrowing the scope to a subdirectory first.
- If the repo is dirty at the start, do not proceed.
