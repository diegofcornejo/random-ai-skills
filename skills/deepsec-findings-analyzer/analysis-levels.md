# Analysis Levels Protocol

Detailed instructions for each of the 3 analysis levels.

## Level 1: Quick Summary

**Goal**: Help the user get oriented in <30 seconds of reading. No interpretation, no AI reasoning beyond what's in the JSON.

### Operations to perform

1. Run `scripts/stats.py <findings_path>` to get base statistics.
2. Run `scripts/group.py <findings_path> --by slug-module` for grouping.
3. Identify hot spots (files with 3+ findings).
4. Identify low-confidence findings (candidates for dismissal).
5. Format using the Level 1 template in `report-templates.md`.

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
   - Severity (CRITICAL > HIGH > MEDIUM > BUG)
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

### Operations to perform

1. Run all Level 2 operations first.
2. Use the Read tool to examine the source files referenced by the top findings (CRITICAL + HIGH at minimum, more if budget permits).
3. For each examined finding:
   - Verify the line numbers and context match what the agent described
   - Identify any upstream mitigations the agent may have missed
   - Note related code that might also need changes
4. For each TP that's actionable, propose a concrete fix:
   - Show the problematic code (use the actual lines, not paraphrased)
   - Show the suggested replacement
   - Note any tests that should be added/updated
5. Identify findings that the user might want to dismiss after seeing the code (e.g., the agent missed an upstream check).
6. Format using the Level 3 template.

### Code reading strategy

- Don't read every file. Budget the reads:
  - Always read files referenced by CRITICAL findings
  - Read files referenced by HIGH findings if there are <20
  - For MEDIUM and BUG, only read on user request during drill-down
- When reading, fetch a generous range around the line numbers (e.g., ±20 lines) to understand context.
- If two findings are in the same file, read once and analyze together.

### Reasoning to apply

After reading the code:

- **Can I confirm the vulnerability?** If yes, proceed with fix.
- **Did the agent miss a mitigation?** If yes, flag this as a candidate to mark FP, with clear reasoning.
- **Is the fix obvious or does it need design decisions?** If design decisions are needed, list the options instead of picking one.
- **Are there related issues nearby?** If yes, mention them but don't expand scope without asking.

### Critical guardrails

- **Never write code to disk** without the user's explicit instruction. Suggest patches in the report, don't apply them.
- **Never claim a fix is complete without tests**. Always recommend test additions.
- **Don't read more than necessary**. Token cost matters; the user is already paying for the deepsec scan.
- **If a fix requires breaking changes or migration**, say so explicitly. Don't gloss over it.

## Drill-down responses (all levels)

After the initial report, the user may ask for more detail. Common requests and how to respond:

- **"Show me details of group X"** → Expand that group: list all findings with titles, paths, line numbers, and short reasoning summaries.
- **"Explain finding Y"** → Quote the agent's reasoning verbatim, add interpretive context only if helpful.
- **"Why is finding Z a false positive?"** → If JSON says FP, quote the revalidation reasoning. If user thinks it's FP but JSON says TP, work with them but don't override without justification.
- **"Generate a ticket draft for X"** → Produce a ready-to-paste markdown ticket with: title, severity, description, reproduction steps (from the agent's reasoning), suggested fix scope, suggested labels.
- **"Group findings by Y"** → Re-group on the requested criterion using the JSON data.
- **"What's the suggested fix for X?"** → If user is at Level 1 or 2, escalate to Level 3 for that finding only (read the file, suggest fix). If at Level 3, refer to what was already produced.
