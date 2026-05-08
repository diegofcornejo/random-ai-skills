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

### Step 3: Privacy reminder

Before producing any output, briefly remind the user:

> 🔒 Note: `findings.json` contains code snippets and exploitation reasoning for real vulnerabilities. Keep it out of public repos and don't paste its contents into untrusted services. The reports I generate will summarize findings but you should still review where you store them.

### Step 4: Ask for analysis depth

Ask the user which level of analysis they want. Use this exact wording:

```
What level of analysis do you want?

**[1] Quick summary** — Deterministic grouping and statistics. Fast, no code reading. Best for getting oriented quickly.

**[2] Pattern analysis** — Everything in [1] plus root-cause detection across findings, prioritization plan, and identification of "fix-once-resolves-many" groups. Recommended starting point.

**[3] Deep analysis** — Everything in [2] plus reading the affected source files, validating findings against the actual code, and proposing concrete fix snippets. Most thorough, uses the most tokens.

Type 1, 2, or 3.
```

Wait for the response. Default to [2] if the user is ambiguous.

### Step 5: Generate the report

Run the analysis at the level the user chose. See `analysis-levels.md` for the detailed protocol of each level.

Output a single Markdown document. Do NOT split across multiple files. The user wants a portable artifact they can paste into a ticket, share with their team, or save.

### Step 6: Offer drill-down

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

What would you like to explore?
```

Then wait for user input. For drill-down requests, refer to the relevant finding(s) in the JSON and respond accordingly. Be specific — quote line numbers, paths, and the agent's original reasoning when relevant.

## Critical rules

- **Never** invent findings, severity ratings, or verdicts. All claims must come from the JSON.
- **Never** suggest a finding is a false positive unless the JSON's `revalidation.verdict` says so OR the user provides convincing context that supersedes the deepsec verdict.
- **Quote** original reasoning from the agent when summarizing. Don't paraphrase to the point of losing technical precision.
- **Respect privacy**: do not write the full content of findings to disk unless the user asks. Reports go to chat unless requested otherwise.
- **Don't run `deepsec export`** without explicit user permission.
- **Don't read source files** unless the user chose level [3] analysis or asks during drill-down.

## File references

- `analysis-levels.md` — Detailed protocol for each of the 3 analysis levels
- `report-templates.md` — Markdown templates for each level's report output
- `scripts/validate.py` — Validates that a file is a valid deepsec JSON export
- `scripts/stats.py` — Computes deterministic statistics (use for level [1] and as foundation for [2] and [3])
- `scripts/group.py` — Groups findings by various criteria (slug+module, file, severity)
- `scripts/merge-triage.py` — Workaround for [deepsec#64](https://github.com/vercel-labs/deepsec/issues/64): reads triage data from FileRecords and injects it into the JSON export
- `examples/` — Example reports at each level for reference
