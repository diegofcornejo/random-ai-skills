# deepsec-findings-analyzer

A Claude Code skill for triaging security findings from [deepsec](https://github.com/vercel-labs/deepsec) — Vercel's security harness powered by coding agents.

## What it does

After running a deepsec scan, you typically end up with dozens or hundreds of findings. Reviewing them one by one is exhausting and error-prone. This skill helps you:

- **Get oriented fast** — instant summary by severity, category, and hot-spot files
- **Find patterns** — detect findings that share a root cause and can be fixed together
- **Plan your attack** — get a prioritized action plan grouped by impact and effort
- **Drill down on demand** — ask follow-up questions about specific findings or groups
- **Generate ticket drafts** — turn findings into copy-paste-ready issues for your tracker
- **Persist progress across sessions** — mark findings as `in-progress`, `wont-fix`, `needs-review`, or `fixed-manual`; the skill resumes where you left off next time

## How to use

### 1. Generate the JSON export from deepsec

After your scan, export findings as JSON:

```bash
cd .deepsec
npx deepsec export --format json --include-resolved --out findings.json
```

`--include-resolved` keeps findings revalidated as `fixed`, `false-positive`, `accepted-risk` or `duplicate`. deepsec hides them by default; without them the report can't show what is already resolved. To run the scan itself, use deepsec's own `/deepsec` skill.

> ⚠️ Add `findings.json` to your `.gitignore`. It contains code snippets and exploitation reasoning for real vulnerabilities — keep it out of public repos.

### 2. Invoke the skill

In Claude Code, ask Claude to use the skill. Examples that trigger it:

- "Use deepsec-findings-analyzer on `findings.json`"
- "Analyze my deepsec findings"
- "Help me triage the findings from my recent scan"

The skill will:

1. Locate your `findings.json` (or ask where it is)
2. Validate it's a real deepsec export
3. Ask which level of analysis you want
4. Produce a Markdown report
5. Wait for follow-up questions

### 3. Choose your analysis level

The skill offers three levels:

| Level | What it does | Best for |
|-------|--------------|----------|
| **1: Quick summary** | Counts, distributions, hot spots. No interpretation. | Getting oriented in 30 seconds |
| **2: Pattern analysis** | Root-cause detection, cross-cutting patterns, prioritized plan. | Most cases — the recommended starting point |
| **3: Deep analysis** | Reads source code, rules each finding confirmed / mitigated / stale / uncertain, proposes fixes. In Claude Code and OpenCode this runs in parallel `deepsec-finding-verifier` subagents, one per group. | When you're ready to start fixing |

You can move up levels mid-session — start at 1 to get oriented, then ask "do level 3 on the SSRF group".

## Installation

### As a personal skill

```bash
# Clone or download into Claude Code's skills directory
cd ~/.claude/skills/
git clone https://github.com/<your-fork>/deepsec-findings-analyzer
```

### As a plugin (shareable)

Add to your `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "deepsec-findings-analyzer": {
      "source": {
        "source": "github",
        "repo": "<your-fork>/deepsec-findings-analyzer"
      }
    }
  },
  "enabledPlugins": {
    "deepsec-findings-analyzer@deepsec-findings-analyzer": true
  }
}
```

## What you get

### Level 1 example

```markdown
# Deepsec Findings: Quick Summary

**Project:** my-app
**Total findings:** 126

## Severity Distribution
| Severity | Count |
|----------|-------|
| CRITICAL | 1     |
| HIGH     | 11    |
| MEDIUM   | 45    |
| BUG      | 64    |

## Top Vulnerability Categories
| Category | Count |
|----------|-------|
| rate-limit-bypass | 12 |
| acl-check         | 11 |
| cross-tenant-id   | 10 |

## Hot Spots
| File | Findings |
|------|----------|
| src/middleware/rate-limiter.ts | 12 |
| src/modules/webhooks/webhook.service.ts | 7 |
```

### Level 2 example

Adds an executive summary, cross-cutting pattern detection, and a prioritized action plan:

```markdown
## Executive Summary

Most findings cluster in 3 files. The CRITICAL SSRF in webhooks and 2 related
HIGH SSRF findings share a common cause — fixing the validator and adding
redirect handling resolves all 3 at once.

## Recommended Action Plan

### 🔴 P0 — This week

**Group: SSRF in webhook delivery** (3 findings)
- Root cause: validator only checks string hostname; fetch follows redirects
- Files: webhook.service.ts, webhook-dispatcher.service.ts, webhook.validator.ts
- Fix scope: validator refactor + manual redirect handling
- Why prioritized: Reachable from authenticated users; can hit IMDS

[...]
```

### Level 3 example

Adds concrete fix snippets after reading the source code:

```markdown
### Fix: SSRF in webhook delivery

**Current code** (`webhook.service.ts` lines 168-176):
\`\`\`typescript
const response = await fetch(webhook.url, {
  signal: AbortSignal.timeout(10000),
});
\`\`\`

**Proposed fix:**
\`\`\`typescript
const response = await fetch(webhook.url, {
  redirect: 'manual',
  signal: AbortSignal.timeout(10000),
});
if (response.status >= 300 && response.status < 400) {
  throw new Error('Redirects not allowed in webhook delivery');
}
\`\`\`

**Tests to add:**
- 302 redirect to private IP → should be rejected
- DNS rebinding (resolves to public, then private) → should be rejected
```

## Drill-down examples

After the initial report, you can ask things like:

- "Show me the details of the rate-limit-bypass group"
- "Explain the CRITICAL SSRF finding"
- "Generate a ticket for the cross-tenant-id group"
- "Why is finding X marked as a false positive?"
- "Group these by severity instead"

## Privacy notes

- The skill never writes findings to disk unless you ask.
- Reports are generated in chat as Markdown; copy-paste them where you want.
- `findings.json` also carries people's names and emails (assignees, on-call, contributors). To share results, `python3 scripts/redact.py findings.json` writes a copy without paths, code, URLs, project name or people.
- The skill won't run `deepsec export` without explicit permission.
- The skill won't run `deepsec triage` without explicit permission (it costs money or quota).
- The skill won't read your source code unless you choose Level 3 or ask during drill-down.
- The verifier subagent is read-only: no edits, no `deepsec` commands, no running your code. A `mitigated` verdict is only a candidate false positive; the skill offers `deepsec revalidate` (with its cost) instead of marking it.

## Workaround for deepsec issue #64

[deepsec#64](https://github.com/vercel-labs/deepsec/issues/64) is a known bug where `deepsec export` does not include the `triage` field, even after `deepsec triage` has been run. The data is stored correctly in the FileRecords but isn't propagated to exports. Still open as of deepsec 2.3.12.

Also note that `deepsec triage` covers one severity per run (`--severity`, MEDIUM by default).

The skill detects this case and uses `scripts/merge-triage.py` to read triage data directly from the FileRecords and inject it into the export. From then on, analysis proceeds normally with full triage data.

If/when the bug is fixed upstream, this workaround becomes a no-op (the script detects existing triage and skips the merge), so the skill keeps working without changes.

## State persistence (multi-session triage)

Triage of large scans (100+ findings) doesn't fit in one sitting. The skill keeps a sidecar JSON file at:

```
<deepsec data dir>/<projectId>/findings-status.json
```

Default lookup walks `data/<projectId>/`, `.deepsec/data/<projectId>/`, and the parent of `findings.json` to find the right deepsec project directory. If none exists, the sidecar lands next to `findings.json` (with a stderr warning).

### State model

| State | Where it lives | Set by |
|-------|---------------|--------|
| `fixed` | native `metadata.revalidation.verdict` | `deepsec revalidate` (verifies via git history) |
| `false-positive` | native `metadata.revalidation.verdict` | `deepsec revalidate` |
| `accepted-risk` | native `metadata.revalidation.verdict` | manual marker in deepsec (real issue the team accepts) |
| `duplicate` | native `metadata.revalidation.verdict` | `deepsec revalidate` (same issue as another finding in the file) |
| `true-positive` / `uncertain` | native `metadata.revalidation.verdict` | `deepsec revalidate` |
| `in-progress` | sidecar | the skill / user |
| `wont-fix` | sidecar | the skill / user |
| `needs-review` | sidecar | the skill / user |
| `fixed-manual` | sidecar | the skill / user (no git verification) |

Native verdicts always win over sidecar state when both exist for `fixed` / `false-positive` / `accepted-risk` / `duplicate`. The sidecar fills only the gap states deepsec doesn't have. To mark something `fixed` or `false-positive` rigorously, run `deepsec revalidate` — the skill will offer this as a hybrid option whenever you ask to mark a finding fixed/FP.

### Session log

Every skill invocation opens a session entry: timestamps, decisions made, optional one-line summary. When you start a new session, the skill reads the last entry and asks whether to resume from `in-progress`, start a fresh pass over `unreviewed`, or regenerate a full report.

CLI for direct inspection (the skill calls these for you):

```bash
python3 scripts/state.py summary findings.json          # effective state + last session
python3 scripts/state.py orphans findings.json          # sidecar keys with no matching finding
python3 scripts/state.py mark findings.json '<key>' in-progress --session <sid>
python3 scripts/state.py session-open findings.json     # returns sessionId
python3 scripts/state.py session-close findings.json <sid> --summary "..."
```

Finding key format: `<filePath>::<vulnSlug>::<firstLineNumber>`.

> The sidecar is deepsec-data-adjacent, not codebase-adjacent. deepsec's scaffold does **not** gitignore it, and it names vulnerable files. If you want to share triage progress with teammates in a private repo, commit `.deepsec/data/<projectId>/findings-status.json`. Otherwise add it to `.gitignore`.

## What this skill is NOT

- It is **not** a replacement for `deepsec revalidate`. The skill works on top of revalidated findings.
- It is **not** an autofix tool. It proposes fixes; you apply them.
- It does **not** override deepsec's verdicts (TP/FP) without your explicit reasoning.

## Contributing

PRs welcome. Ideas particularly appreciated:

- Better cross-cutting pattern detection
- Support for custom matchers/categories
- Integration with ticket systems (auto-create issues)
- Severity recalibration based on project context

## License

MIT — see `LICENSE`.

## Related

- [deepsec](https://github.com/vercel-labs/deepsec) — the security harness this skill operates on
- [Practical guide to deepsec](https://blog.diegocornejo.com/deepsec-vercel-security-harness-practical-guide) — setup, troubleshooting, and triage walkthrough
