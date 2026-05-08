# Report Templates

Markdown templates for each analysis level. Adapt as needed but maintain the structure for consistency.

## Level 1 Template

```markdown
# Deepsec Findings: Quick Summary

**Project:** {project_id}
**Scan date:** {discoveredAt of most recent finding}
**Total findings:** {N}

## Severity Distribution

| Severity | Count |
|----------|-------|
| CRITICAL | {n} |
| HIGH | {n} |
| HIGH_BUG | {n} |
| MEDIUM | {n} |
| BUG | {n} |

## Revalidation Status

- ✅ True Positives: {n}
- ❌ False Positives: {n}
- 🔧 Already Fixed: {n}
- ❓ Uncertain: {n}

## Top Vulnerability Categories

| Category | Count |
|----------|-------|
| {slug-1} | {n} |
| {slug-2} | {n} |
| ... | ... |

## Hot Spots (files with 3+ findings)

| File | Findings | Categories |
|------|----------|------------|
| {path} | {n} | {top 3 slugs} |
| ... | ... | ... |

## Low-Confidence Findings ({n})

These findings have `confidence: low` and might be safe to dismiss after a quick review:

- {title} — `{path}` (slug: `{slug}`)
- ...

## Quick Stats

- Most affected directory: `{dir}` ({n} findings)
- Average findings per affected file: {avg}
- Files with at least 1 finding: {n}
```

## Level 2 Template

```markdown
# Deepsec Findings: Pattern Analysis

**Project:** {project_id}
**Total findings:** {N} ({TP} true positives, {FP} false positives)
**Scan date:** {date}

## Executive Summary

{2-3 sentences capturing the most important takeaway. Examples:
- "Most findings cluster in 3 files, suggesting refactor-level fixes are highest leverage."
- "The CRITICAL SSRF and several MEDIUM findings share a webhook delivery layer — fix that layer first."
- "Rate limiting issues dominate; a single middleware fix likely resolves 10+ findings."}

## Recommended Action Plan

### 🔴 P0 — This week

{Group findings that are CRITICAL or HIGH and either:
- Have multi-tenancy implications
- Affect authentication/authorization layers
- Have a clear root cause shared across multiple findings}

**Group: {descriptive name}** ({n} findings)
- Root cause: {1 sentence}
- Affected files: `{path 1}`, `{path 2}`, ...
- Estimated fix scope: {single function | helper refactor | architectural change}
- Why prioritized: {explanation}

[repeat for each P0 group]

### 🟡 P1 — Next sprint

{HIGH findings that don't fit P0, plus MEDIUM findings with high impact or clear shared root cause}

**Group: {name}** ({n} findings)
- {same structure}

### 🟢 P2 — Backlog

{MEDIUM findings that are isolated or lower-impact}

### ⚪ P3 — Code quality (BUG severity)

{BUG findings — track but don't block on}

## Detected Patterns

### Cross-Cutting

{Patterns where findings span multiple modules but share a root cause}

- **{Pattern name}**: {description}
  - Affects: {n} findings across {n} modules
  - Likely root cause: {1 sentence}
  - Recommended approach: {single sentence}

### Hot Spots

{Files with 3+ findings, each with explanation of what's likely going on}

- `{path}` ({n} findings, {dominant slugs})
  - {1 sentence on whether this is one root cause or multiple distinct issues}

## False Positive Review

{For the FPs from revalidation, briefly state why deepsec marked them as FP. Don't second-guess the verdicts.}

## Findings Worth Reviewing for Possible Dismissal

{Low-confidence findings the user might want to spot-check before fixing}

## Group Index

{Full list of all groups with their finding counts, for the user to use as drill-down anchors}

| Group | Count | Severity | Priority |
|-------|-------|----------|----------|
| ... | ... | ... | ... |
```

## Level 3 Template

Use the Level 2 template as the base, then add this section at the end:

```markdown
## Concrete Fix Proposals

{For each P0 group and selected P1 groups where code reading was performed}

### Fix: {Group name}

**Affected:** {n} findings — see Group Index above

**Current code** (`{path}` lines {x-y}):
\`\`\`{language}
{verbatim code from file}
\`\`\`

**Issue:** {1-2 sentence explanation of what's wrong, referencing the agent's reasoning}

**Proposed fix:**
\`\`\`{language}
{code with the fix applied}
\`\`\`

**Why this fix works:** {1 sentence}

**Tests to add:**
- {Test description 1}
- {Test description 2}

**Migration notes:** {Only if applicable — breaking changes, schema changes, etc.}

**Estimated effort:** {S | M | L}

---

[repeat for each fix]
```

## Drill-Down Response Templates

### "Show me details of group X"

```markdown
## Group: {Name}

**Findings in this group:** {n}
**Shared root cause:** {1 sentence}
**Recommended approach:** {1 sentence}

### Findings

#### {Title 1}

- **File:** `{path}` lines {x}
- **Severity:** {sev} ({confidence})
- **Slug:** `{slug}`
- **Verdict:** {revalidation verdict}
- **Summary:** {1-2 sentences from agent's reasoning}

#### {Title 2}
... [same structure]
```

### "Generate a ticket draft for X"

```markdown
## Ticket Draft

**Title:** [{SEVERITY}] {Concise problem statement}

**Labels:** security, {slug}, severity:{sev}

**Description:**

{Plain-English problem description, 2-3 paragraphs}

**Affected files:**
- `{path 1}` — lines {x}
- `{path 2}` — lines {y}

**Reproduction:**

{Steps from the agent's reasoning, formatted as numbered list}

**Recommended fix:**

{From the analysis — could be a snippet, a refactor description, or a design decision the team needs to make}

**Acceptance criteria:**

- [ ] {Criterion 1}
- [ ] {Criterion 2}
- [ ] Tests added covering the vulnerability path
- [ ] No regressions on existing test suite

**References:**
- Deepsec finding: {title}
- Agent reasoning: see findings.json or original scan output
```
