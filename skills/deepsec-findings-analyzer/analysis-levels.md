# Analysis Levels Protocol

Detailed instructions for each of the 3 analysis levels.

## Level 1: Quick Summary

**Goal**: Help the user get oriented in <30 seconds of reading. No interpretation, no AI reasoning beyond what's in the JSON.

### Operations to perform

1. Run `scripts/stats.py <findings_path>` to get base statistics.
2. Run `scripts/group.py <findings_path> --by slug-module` for grouping.
3. Identify hot spots (files with 3+ findings).
4. Identify low-confidence findings and findings triaged `skip` (candidates for dismissal).
5. Count resolved findings separately (`fixed`, `false-positive`, `accepted-risk`, `duplicate`): they are history, not work.
6. Format using the Level 1 template in `report-templates.md`.

### Do NOT

- Don't speculate about root causes
- Don't suggest fixes
- Don't read source code
- Don't make priority recommendations beyond what severity dictates

### Output should answer

- How many findings by severity?
- What categories dominate?
- Which files concentrate the most findings?
- What are the false positives (per revalidation)?
- What's worth dismissing first (low confidence)?

## Level 2: Pattern Analysis

**Goal**: Help the user plan their attack. Identify root causes, group findings that likely share a single fix, and produce a prioritized action plan.

### Operations to perform

1. Run all Level 1 operations first.
2. For each group with 2+ findings, examine the titles and descriptions to determine if they share a root cause.
3. Identify cross-cutting patterns:
   - Same vulnerability slug across multiple modules → likely a missing helper/middleware
   - Multiple slugs in the same file → likely a single high-risk component
   - Same module appearing in multiple groups → likely a hot spot needing refactor
4. Produce a prioritized action plan ordered by:
   - Triage priority, when present (`metadata.triage.priority`: P0 > P1 > P2; `skip` goes to the dismissal candidates, never silently dropped). Quote its `exploitability` / `impact` when they explain the call.
   - Severity (CRITICAL > HIGH > HIGH_BUG > MEDIUM > BUG > LOW)
   - Group size (a group of 10 findings beats an isolated finding at the same severity, because one fix resolves many)
   - Confidence (HIGH confidence beats MEDIUM/LOW)
5. Format using the Level 2 template.

### Reasoning to apply

When grouping findings, consider:

- **Same slug + same file** = almost certainly one root cause, one fix
- **Same slug + same module + similar titles** = likely shared helper/pattern
- **Same slug + different modules** = could be a missing utility everyone reimplements badly, OR could be coincidental
- **Different slugs + same file** = the file is high-risk, multiple distinct issues
- **CRITICAL alone in a group** = treat as urgent regardless of group dynamics
- **`duplicate` verdicts** = fold them into their primary finding (same file); count the group once

### Things to flag explicitly

- Any CRITICAL or HIGH findings that share a file (compounding risk)
- Multi-tenancy issues (`cross-tenant-id` slug) — these are often data exfiltration risks
- Auth-related slugs in middleware files — these affect every route
- Rate limiting issues at the middleware layer — single fix usually
- Race conditions in the same module — could be locking strategy issue

### Do NOT

- Don't read source code (that's Level 3)
- Don't propose code patches
- Don't override deepsec's verdicts (TP/FP) unless the user explicitly asks

## Level 3: Deep Analysis

**Goal**: Validate findings against actual code and propose concrete fixes.

The code-reading procedure, verdicts (`confirmed` / `mitigated` / `stale` / `uncertain`) and the **Verification Report** format live in [references/verification.md](references/verification.md). It is read-only.

### Operations to perform

1. Run all Level 2 operations first.
2. **Pick what to verify** (token cost matters; the user already paid for the scan):
   - Always: every group with a CRITICAL finding.
   - HIGH groups if there are fewer than 20 HIGH findings; otherwise the top ones by triage priority / group size, and say what was left out.
   - MEDIUM, BUG and LOW only on request during drill-down.
   - Skip resolved findings (`fixed`, `false-positive`, `accepted-risk`, `duplicate`) and sidecar `wont-fix`.
   - Split a group larger than ~8 findings, keeping findings of the same file together.
3. **Verify each group: delegate or inline.**

   | Environment | How |
   |-------------|-----|
   | Claude Code | `Agent` tool, `subagent_type` `deepsec-finding-verifier` (plugin install: `deepsec-findings-analyzer:deepsec-finding-verifier`). One agent per group; launch independent groups in the same message so they run in parallel (at most ~5 at once). |
   | OpenCode | The `deepsec-finding-verifier` subagent (or `@deepsec-finding-verifier`), one per group. |
   | No subagent | Read `references/verification.md` and follow it yourself, group by group. |

   Delegation prompt (absolute paths):

   ```text
   Verify these deepsec findings (protocol Phases 1–4) and return ONLY the Verification Report.
   Protocol file: <skill-dir>/references/verification.md
   Skill dir: <skill-dir>
   Findings file: <absolute path to findings.json (or the merged file)>
   Source root: <absolute path to the scanned codebase>
   Group: <label, e.g. "ssrf in src/api">
   Keys:
   - <filePath>::<vulnSlug>::<firstLine>
   - ...
   Budget: 8 files per finding
   Read-only: no edits, no deepsec commands, no running the code.
   ```

4. **Treat each report as evidence, not truth.** Before showing it:
   - Every `mitigated` row (a candidate false positive): read the cited mitigation line yourself.
   - Every fix proposal: spot-check that its "current code" matches the file at the cited lines.
   - Rows without `path:line` evidence count as `uncertain`.
5. Merge the reports into the Level 3 template (`report-templates.md`): verdict table, fix proposals per root cause, and "candidates to revalidate" for `mitigated` / `stale` rows. Offer `deepsec revalidate` for those with the cost disclosure from SKILL.md; never mark them yourself.

### Critical guardrails

- **Never write code to disk** without the user's explicit instruction. Suggest patches in the report, don't apply them.
- **Never claim a fix is complete without tests**. Always recommend test additions.
- **If a fix requires breaking changes or migration**, say so explicitly. Don't gloss over it.
- **Never change a finding's state from a verifier verdict alone.** `mitigated` and `stale` are recommendations; the user decides, and `deepsec revalidate` gives the native verdict.

## Drill-down responses (all levels)

After the initial report, the user may ask for more detail. Common requests and how to respond:

- **"Show me details of group X"** → Expand that group: list all findings with titles, paths, line numbers, and short reasoning summaries.
- **"Explain finding Y"** → Quote the agent's reasoning verbatim, add interpretive context only if helpful.
- **"Why is finding Z a false positive?"** → If JSON says FP, quote the revalidation reasoning. If user thinks it's FP but JSON says TP, work with them but don't override without justification.
- **"Generate a ticket draft for X"** → Produce a ready-to-paste markdown ticket with: title, severity, description, reproduction steps (from the agent's reasoning), suggested fix scope, suggested labels.
- **"Group findings by Y"** → Re-group on the requested criterion using the JSON data.
- **"What's the suggested fix for X?"** → If user is at Level 1 or 2, escalate to Level 3 for that finding only (one verifier run, or the protocol inline for a single finding). If at Level 3, refer to what was already produced.
