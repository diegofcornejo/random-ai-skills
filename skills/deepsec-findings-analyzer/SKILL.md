---
name: deepsec-findings-analyzer
description: Analyze and triage findings from a deepsec security scan. Use when the user has run `deepsec export --format json` (or wants to) and needs help understanding, grouping, prioritizing, or planning fixes for the findings. Triggers on mentions of deepsec, security findings, vulnerability triage, security scan results, or when a `findings.json` file is present.
---

# Deepsec Findings Analyzer

A skill for triaging security findings produced by [deepsec](https://github.com/vercel-labs/deepsec), Vercel's security harness powered by coding agents.

## When to use this skill

Use this skill when the user:
- Has just run a deepsec scan and asks for help understanding the findings
- Wants to triage, prioritize, or plan fixes for deepsec findings
- Has a `findings.json` file from `deepsec export --format json`
- Mentions "deepsec findings", "security scan results", or similar
- Asks for help with vulnerability triage or remediation planning

## Script paths

Every `scripts/…` path in this skill is relative to **this skill's directory** (the folder containing this `SKILL.md`), not to the user's project. Before running one, resolve it to an absolute path — e.g. `python3 <skill-dir>/scripts/state.py summary <findings.json>` — while keeping the user's project as the working directory. Running `python3 scripts/state.py` from the project root will fail with "No such file".

## Workflow

Follow this workflow strictly. Do not skip steps.

### Step 1: Locate the findings file

The skill operates on a JSON export from deepsec. To find it:

1. **First**, check if the user provided a path explicitly. If so, use it.
2. **If not**, check the current working directory for `findings.json`.
3. **If not found in cwd**, check common locations: `./findings.json`, `.deepsec/findings.json`, `./out/findings.json`.
4. **If still not found**, ask the user:

   ```
   I couldn't find a findings.json file. You have three options:

   1. **Generate it now** — I can run `deepsec export --format json` for you (requires deepsec to be installed and a project configured). Note: this may overwrite an existing file. This step has no AI cost.

   2. **Provide the path** — If you have one elsewhere, tell me where.

   3. **You generate it** — Run `pnpm deepsec export --format json --out findings.json` from your `.deepsec/` directory and tell me when done.

   Which would you like?
   ```

   Wait for the user's response before proceeding. **Never run `deepsec export` without explicit permission** — it can overwrite files.

### Step 2: Check if triage data is present

After locating `findings.json`, run `scripts/validate.py <path>` to confirm it's a valid deepsec export. If validation fails, tell the user clearly and stop.

Then check whether the findings have been triaged. The skill produces better, more accurate priority recommendations when `deepsec triage` has been run, because triage adds `priority` (P0/P1/P2), `exploitability`, `impact`, and structured `reasoning` fields to each finding.

Run this check:

```bash
python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
triaged = sum(1 for f in data if f.get('metadata', {}).get('triage'))
print(f'{triaged}/{len(data)}')
" <path_to_findings.json>
```

**If triage is present in some/all findings:** Proceed to Step 3.

**If triage is missing from all findings:** This may be because (a) the user hasn't run `deepsec triage` yet, or (b) they ran triage but it's affected by the known export bug ([deepsec#64](https://github.com/vercel-labs/deepsec/issues/64)) where the field exists in FileRecords but isn't included in exports. To distinguish:

```bash
# Check if triage data exists in FileRecords (bypassing the export bug)
find data/*/files -name "*.json" -exec grep -l '"triage"' {} \; 2>/dev/null | head -1
```

- **If FileRecords contain triage but the export doesn't** → The user is hitting issue #64. Tell them the bug is being tracked and offer to merge the triage data from the FileRecords into the export. Use `scripts/merge-triage.py`:

   ```bash
   python3 scripts/merge-triage.py <findings.json> <data/<project-id>/files/> <output.json>
   ```

   The script reads each FileRecord, extracts the `triage` field for each finding, and writes a new JSON file with triage injected. From then on, use the merged file as the source of truth for the rest of the analysis.

   Tell the user something like:
   ```
   Your findings.json doesn't include triage data due to a known bug
   (deepsec#64). I found the data in your FileRecords though, so I'll merge
   it into a new file (findings.merged.json) and continue from there.
   ```

   Run the merge, then use the merged file for Steps 3 onwards.

- **If FileRecords don't contain triage either** → The user simply hasn't run `deepsec triage`. Offer them the choice with full transparency on cost:

   ```
   Your findings haven't been triaged yet. You have two options:

   1. **Run `deepsec triage` now** — This will use AI (claude-sonnet-4-6 by default) to assign priority (P0/P1/P2), exploitability rating, impact rating, and reasoning to each finding. **This has a real cost: roughly $0.01 per finding** (or equivalent quota usage if you use a Claude subscription). For a typical scan of ~100 findings that's around $1, but you should confirm before proceeding. The triage results persist in deepsec's data/ directory and can be re-exported.

   2. **Skip triage and analyze locally** — I'll analyze your findings without AI-assisted triage. The plan I produce will use my own heuristic prioritization based on severity, vulnSlug, confidence, and grouping patterns. This costs nothing extra beyond our current conversation. The trade-off is that priority calls will be less rigorous than what `deepsec triage` produces, since I rely on rules of thumb rather than per-finding analysis.

   Which would you prefer?
   ```

   Wait for the user's response. **Never run `deepsec triage` without explicit permission** — it costs money (or quota) and the user must consent.

### Step 3: Load state sidecar and show resume hint

The skill is multi-session. Native deepsec verdicts (`metadata.revalidation.verdict`) cover `fixed` and `false-positive`, but human-curated states like `in-progress`, `wont-fix`, `needs-review`, and `fixed-manual` live in a sidecar at `<deepsec data dir>/<projectId>/findings-status.json`. The sidecar also stores a session log so the skill can answer "what did we do last time?".

Run:

```bash
python3 scripts/state.py summary <findings.json>
```

This prints the effective state distribution (sidecar + native verdicts merged) and the last session's id, timestamps, and summary. Use it to:

1. **Greet the user with a resume context** when a previous session exists. Example:

   ```
   I see you ran a session on 2026-05-07 ("Triaged P0 SSRF group, 3 in-progress").
   Current state: 12 unreviewed, 3 in-progress, 5 wont-fix, 8 native:fixed,
   2 native:false-positive, 92 native:true-positive (out of 122).

   Want to (a) resume from in-progress, (b) start a new pass over unreviewed,
   or (c) generate a fresh full report?
   ```

2. **Skip already-decided findings** in subsequent analysis unless the user asks to re-open. `native:fixed` and `native:false-positive` should be excluded from "to-fix" plans by default. `wont-fix` likewise.

3. **Detect orphans** if findings.json was regenerated and some sidecar keys no longer match. Run `python3 scripts/state.py orphans <findings.json>` and report them; let the user decide (re-key manually, or leave as historical record). Never auto-delete sidecar entries.

If the sidecar doesn't exist yet, the summary will show `Exists: False` and 0 sessions — that's fine, this is a first run.

**Effective state precedence** (state.py implements this; do not second-guess it):

1. `revalidation.verdict == "fixed"` → wins (verified via git history).
2. `revalidation.verdict == "false-positive"` → wins (verified by AI).
3. Sidecar state (`in-progress`, `wont-fix`, `needs-review`, `fixed-manual`) → wins over `true-positive` and `uncertain`.
4. `revalidation.verdict == "true-positive"` → fallback.
5. `revalidation.verdict == "uncertain"` → fallback.
6. None of the above → `unreviewed`.

### Step 4: Privacy reminder

Before producing any output, briefly remind the user:

> 🔒 Note: `findings.json` contains code snippets and exploitation reasoning for real vulnerabilities. Keep it out of public repos and don't paste its contents into untrusted services. The reports I generate will summarize findings but you should still review where you store them.

### Step 5: Ask for analysis depth

Ask the user which level of analysis they want. Use this exact wording:

```
What level of analysis do you want?

**[1] Quick summary** — Deterministic grouping and statistics. Fast, no code reading. Best for getting oriented quickly.

**[2] Pattern analysis** — Everything in [1] plus root-cause detection across findings, prioritization plan, and identification of "fix-once-resolves-many" groups. Recommended starting point.

**[3] Deep analysis** — Everything in [2] plus reading the affected source files, validating findings against the actual code, and proposing concrete fix snippets. Most thorough, uses the most tokens.

Type 1, 2, or 3.
```

Wait for the response. Default to [2] if the user is ambiguous.

### Step 6: Open a session

Before doing any analysis or letting the user mutate state, open a session in the sidecar:

```bash
python3 scripts/state.py session-open <findings.json>
```

It prints a `sessionId` on stdout. Hold onto it — every state mutation in this conversation should pass `--session <id>` so the decision log is grouped under one session entry. If the user makes no decisions, the session stays empty (harmless).

### Step 7: Generate the report

Run the analysis at the level the user chose. See `analysis-levels.md` for the detailed protocol of each level.

Output a single Markdown document. Do NOT split across multiple files. The user wants a portable artifact they can paste into a ticket, share with their team, or save.

When the report is generated for a session that already has prior state, exclude `native:fixed`, `native:false-positive`, and `wont-fix` findings from the "to-fix" plan by default. Show them in a separate "previously decided" section so the user can scan the history without losing focus on actionable work.

### Step 8: Offer drill-down and state mutation

After delivering the report, end with:

```
---

The report is ready. You can ask me follow-up questions like:

- "Show me the details of the [group name] group"
- "Explain finding [title]"
- "Why is [finding] marked as a false positive?"
- "What's the recommended fix for [finding]?"
- "Group findings differently — by [criterion]"
- "Generate a ticket draft for [group/finding]"

Or update state across the session:

- "Mark [finding] as in-progress"
- "Mark [finding] as wont-fix"
- "Mark [group] as needs-review"
- "Show me everything that's in-progress"

When you're done, say "wrap up" and I'll save a session summary so we can pick up next time.
```

Then wait for user input. For drill-down requests, refer to the relevant finding(s) in the JSON and respond accordingly. Be specific — quote line numbers, paths, and the agent's original reasoning when relevant.

#### State mutation rules

When the user asks to mark a finding's state, run:

```bash
python3 scripts/state.py mark <findings.json> <key> <state> --session <sessionId>
```

The key format is `<filePath>::<vulnSlug>::<firstLineNumber>`. To find a key for a finding the user named, look it up in the JSON yourself — never ask the user for the raw key.

**Hybrid path for `fixed` and `false-positive`** (these are native deepsec verdicts; the sidecar's `fixed-manual` is a fallback):

- If the user says "this is fixed" → first ask whether they want a rigorous verification, **and disclose that revalidate has a real cost**:

  ```
  I can verify this two ways:

  (a) Run `deepsec revalidate` scoped to this finding. Deepsec re-investigates
      with AI + git history and produces a native `revalidation.verdict=fixed`
      verdict that wins precedence over any sidecar state. **This costs real
      money or quota** — deepsec docs put `revalidate` "comparable to `process`"
      (architecture.md), and `process` is the expensive stage (~$0.25–$0.60 per
      file at batch scale, with cost swinging 2–3x on file complexity, per
      docs/faq.md). Single-file scoped runs aren't priced in the docs and may
      run higher relative to per-file batch averages. Use `--limit` or run on
      one file first to calibrate before committing to a larger batch.

  (b) Mark `fixed-manual` in the sidecar immediately. Free and instant, but no
      verification — if you're wrong, the bug stays open and the sidecar lies.

  Which do you prefer?
  ```

  Default-recommend (a) for high/critical severity, (b) for low/bug. Always show the cost disclosure — never run revalidate without the user seeing it first.

- If the user says "this is a false positive" → strongly recommend `deepsec revalidate` (the native verdict carries `false-positive` cleanly), **but show the same cost disclosure**. Only use sidecar `wont-fix` if the user explicitly wants to dismiss without re-validation.

- **Batching tip.** If the user wants to verify multiple findings in the same file, group them with `--filter <path> --only-slugs <slug,…>` so revalidate covers all of them in one run. Co-located findings revalidate together — fewer separate runs means less setup overhead.

**Wrap-up.** When the user says "wrap up", "done", "save and exit", or similar:

1. Generate a one-line summary of the session (decisions made, groups touched).
2. Run:

   ```bash
   python3 scripts/state.py session-close <findings.json> <sessionId> --summary "..."
   ```

3. Tell the user the sidecar path so they know where state persists.

## Critical rules

- **Never** invent findings, severity ratings, or verdicts. All claims must come from the JSON.
- **Never** suggest a finding is a false positive unless the JSON's `revalidation.verdict` says so OR the user provides convincing context that supersedes the deepsec verdict.
- **Quote** original reasoning from the agent when summarizing. Don't paraphrase to the point of losing technical precision.
- **Respect privacy**: do not write the full content of findings to disk unless the user asks. Reports go to chat unless requested otherwise.
- **Don't run `deepsec export`** without explicit user permission.
- **Don't read source files** unless the user chose level [3] analysis or asks during drill-down.
- **Don't run `deepsec revalidate`** without explicit user permission AND a visible cost disclosure pointing to deepsec's official cost guidance ([faq.md](https://github.com/vercel-labs/deepsec/blob/main/docs/faq.md), [architecture.md](https://github.com/vercel-labs/deepsec/blob/main/docs/architecture.md)). Asking permission without flagging that there's a real cost is not consent. Don't quote specific dollar amounts the docs don't guarantee.
- **Native verdicts win.** Never override `revalidation.verdict=fixed` or `=false-positive` with a sidecar state. The sidecar fills the gap states deepsec doesn't have; it doesn't replace deepsec's own.
- **Never auto-delete sidecar entries.** Orphans (sidecar keys with no matching finding) are reported, not removed.

## File references

- `analysis-levels.md` — Detailed protocol for each of the 3 analysis levels
- `report-templates.md` — Markdown templates for each level's report output
- `scripts/validate.py` — Validates that a file is a valid deepsec JSON export
- `scripts/stats.py` — Computes deterministic statistics (use `--state` for effective state distribution)
- `scripts/group.py` — Groups findings by various criteria (slug+module, file, severity)
- `scripts/merge-triage.py` — Workaround for [deepsec#64](https://github.com/vercel-labs/deepsec/issues/64): reads triage data from FileRecords and injects it into the JSON export
- `scripts/state.py` — Sidecar state manager: load/mark/session-open/session-close/orphans/summary
- `examples/` — Example reports at each level for reference
