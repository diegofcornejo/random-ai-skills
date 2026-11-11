---
name: github-security-remediation
description: Use when planning or fixing a GitHub repository's open security alerts, or when producing a daily consolidated security report for one or more GitHub orgs or user accounts. Triggers on "security alerts", "Security tab", "Dependabot", "Dependabot alerts/PRs", "code scanning", "CodeQL", "secret scanning", "vulnerabilities", "GHSA", "CVE", "security report", "daily security report", "remediation plan", "SECURITY-REMEDIATION.md", "drive alerts to zero", or "progress for the security team". Covers Angular, JavaScript/TypeScript (npm, yarn, pnpm) and PHP (Composer) on github.com, GHE Cloud and GHE Server via the gh CLI.
---

# GitHub Security Remediation

Turn GitHub's security alerts (Dependabot, code scanning, secret scanning) into action:

- **Repo mode**: diagnose the current repository → write a remediation plan → execute the approved blocks with the developer.
- **Portfolio mode**: one consolidated daily report across one or more owners (orgs or users), with day-over-day deltas, for the security team.

Numbers always come from the scripts (GitHub API data via `gh`). You never estimate or recompute them. You write the analysis and the recommendations on top of them.

This skill is the **orchestrator**. It owns the conversation, the plan, approvals and every write. The heavy, read-only repo analysis can be delegated to the `security-alerts-analyzer` subagent or run inline.

## 1. First-run notice

Show it only when it is new to the user: in repo mode, only when `.github-security-remediation.json` does not exist at the repo root yet (Step 4 always creates it, so it is shown once per repo); in portfolio mode, when there is no earlier day folder under `<out>/<scope>/`, at most once per conversation. Say it briefly, **in the user's language**, right after the preconditions and before the analysis or the fetch. Translate it; do not paste the English if the user writes in another language.

Repo mode:

> I'll read this repo's security alerts (Dependabot, code scanning, secret scanning) and write a remediation plan, `SECURITY-REMEDIATION.md`, grouped into blocks with priority, fix-risk and effort. Before acting I will ask you: whether to version the plan or keep it out of git; which blocks to execute; before every change to application code; before every alert dismissal; and to confirm any secret rotation done outside the repo. I work on a separate branch with one commit per block. I never push, open PRs or merge: you choose how to integrate.

Portfolio mode:

> I'll fetch the security alerts for the owners you name and produce today's report folder: `report.html` (self-contained, printable to PDF), `summary.txt` (paste-able), `snapshot.json` and `diff.json`, with the change since the previous report. Before acting I will confirm the owner list and output folder, and ask whether the reports should be versioned if the folder is inside a git repo. I change nothing on GitHub.

## 2. Language rule

- All skill files are English. **Everything the user sees is in the language the user is speaking**: your answers, every question, the approval prompt, `SECURITY-REMEDIATION.md`, dismissal comments, the portfolio narrative, and the report (pass that language to the report script as `--lang <code>`, ISO 639-1, e.g. `es`).
- The HTML/summary templates ship `en` and `es`. For any other language the script falls back to English (it prints a warning). Tell the user, and still write the narrative and the conversation in their language.
- Never translate: package names, versions, GHSA/CVE ids, rule ids, file paths, commands, branch names, numbers, and API enum values such as dismissal reasons (`tolerable_risk`, `false positive`, `revoked`).
- If the user switches language, switch with them.
- Internal artifacts (the Analysis Report from the subagent, script JSON) stay as they are; you translate when you write for the user.

## 3. Script paths

Every `scripts/…` and `references/…` path in this skill is relative to **this skill's directory** (the folder containing this `SKILL.md`), not to the user's project. Resolve `<skill-dir>` once:

- the base directory this skill was loaded from (e.g. `~/.claude/skills/github-security-remediation`, `.claude/skills/github-security-remediation`, `.agents/skills/github-security-remediation`), or
- in a Claude Code plugin install, `${CLAUDE_PLUGIN_ROOT}/skills/github-security-remediation`.

Then run scripts as `python3 <skill-dir>/scripts/<cli>.py …` with an **absolute** path, keeping the user's project as the working directory. `python3 scripts/analyze_repo.py` from the project root fails with "No such file".

| CLI | Purpose | Writes |
|-----|---------|--------|
| `analyze_repo.py [--repo OWNER/NAME] [--host H]` | One repo: snapshot + open Dependabot PRs + repo meta + Autofix status | nothing (JSON to stdout) |
| `run_portfolio.py (--owner X [--owner Y …] \| --repo OWNER/NAME [--repo …]) [--host H] [--out DIR] [--lang L] [--include-archived] [--date YYYY-MM-DD]` | Fetch, snapshot, diff and render a report day, for whole owners or only the named repos | `<out>/<scope>/<date>/` |
| `render_report.py --dir DAY_DIR [--lang L] [--narrative FILE]` | Re-render `report.html` + `summary.txt` for a day folder | the day folder |
| `secret_redact.py show PATH START END --commit SHA [--start-column C --end-column C]`, `secret_redact.py replace PATH START END --commit SHA` (stdin), `secret_redact.py diff [--cached \| --commit REV] [PATH …]` | View (exact column span masked, or whole line redacted), replace, and diff (structure only) secret-bearing lines; never prints the value; `show`/`replace` refuse a location that changed since the alert's `commit_sha` ([playbooks/secrets.md](references/playbooks/secrets.md)) | `replace` edits that file only |
| `dismiss.py --repo O/N --source dependabot\|code_scanning\|secret_scanning --number N --reason R --comment TEXT [--host H] [--dry-run]` | Dismiss/resolve one alert (validated reason, ≤280-char comment) | one PATCH on GitHub |

**Error contract.** On failure a CLI prints one JSON line `{"error": "...", "hint": "..."}` to stdout and exits non-zero (2; `render_report.py` exits 1). Status goes to stderr. When you see it: stop, tell the user the error and the hint in their language (e.g. "Run: `gh auth login`", "Run: `gh auth refresh -s security_events`"), and wait. Do not retry in a loop and do not work around it with hand-written `gh api` calls.

## 4. Mode router

| Mode | Pick it when the request mentions… |
|------|------------------------------------|
| **Repo** | analyzing / planning / fixing security alerts for *this* repo; "vulnerabilities", "Dependabot", "code scanning", "secret scanning", "Security tab", a GHSA/CVE id in this repo, "remediation plan", `SECURITY-REMEDIATION.md` |
| **Portfolio** | the organization or an org name, "all repos", several owners, a consolidated or daily report, "security report" for a team, progress or proof for the security team; also an **HTML / daily report for this repo or named repos** (run with `--repo`) |

- If the request fits both or neither (e.g. "security report" inside a repo, no owner named), **ask**: "Only this repository (plan and fixes), a daily HTML report for this repository, or a consolidated report for one or more owners?" Do not guess.
- "Only analyze / only a report, no changes" in repo mode: run steps 1–4 (Step 4 asks the report-file decision, with the public-repo warning, before any plan file is written), present the plan as in Step 5 without the approval question, and stop. If the user wants no file at all, present the plan in the conversation only and still ask before writing anything.

## 5. Repo mode

Follow the steps in order. Do not skip any.

### Step 1 — Preconditions (main thread)

1. **Tools**: `gh --version` and `python3 --version` (3.9+). Missing `gh` → stop and point to https://cli.github.com.
2. **Repo and host**: `git rev-parse --show-toplevel`, `git remote get-url origin` (the host is the remote's host: `github.com`, `*.ghe.com`, or a GHE Server hostname), then `gh repo view --json nameWithOwner,visibility,defaultBranchRef,url`.
3. **Auth**: `gh auth status --hostname <host>`. Not logged in → ask the user to run `gh auth login --hostname <host>` themselves. Code scanning and secret scanning on private repos need a token with `security_events` (classic tokens): if it is missing, ask the user to run `gh auth refresh -s security_events` (interactive; never run it for them).
4. **Working tree**: `git status --porcelain`. If it is dirty, **stop and ask** the user to commit or stash first. Exception: if the only changes are this skill's own files (`SECURITY-REMEDIATION.md`, `.github-security-remediation.json`, or the `.gitignore` line this skill added) and `git diff -- .gitignore` shows exactly that one added line, say so and continue.
5. **Visibility**: record `PUBLIC`, `PRIVATE` or `INTERNAL`. It drives the report-file decision (section 7).
6. Show the first-run notice (section 1) if `.github-security-remediation.json` does not exist yet.

### Step 2 — Analysis: delegate or inline

The protocol and the **Analysis Report** format live in [references/repo-analysis.md](references/repo-analysis.md). It is read-only.

| Environment | How to run it |
|-------------|---------------|
| Claude Code | `Agent` tool with `subagent_type` `security-alerts-analyzer` (plugin install: `github-security-remediation:security-alerts-analyzer`) |
| Anything else, or the subagent is not available | Run it **inline**: read `references/repo-analysis.md` and follow it yourself |

Delegation prompt. Fill every placeholder, and pass **absolute** paths (`<skill-dir>` resolved as in section 3):

```text
Run the GitHub security alerts analysis protocol and return ONLY the Analysis Report.
Protocol file: <skill-dir>/references/repo-analysis.md
Skill dir (scripts live in <skill-dir>/scripts/): <skill-dir>
Project root: <absolute path of the repo>
Repo: <owner/name> · Host: <host> · Visibility: <PUBLIC|PRIVATE|INTERNAL> · Default branch: <name>
Working tree: <clean | only skill files changed>
Extra context from the user: <anything relevant, e.g. "billing module is legacy", "we must stay on PHP 7.4">
Read-only: do not edit, write, install, commit, push, dismiss, or call any non-GET API. Never print secret values.
```

**Treat the report as evidence, not truth.** Before building the plan, spot-check every row you will put in a block (one cheap check each):

- dependency rows: confirm the installed version and direct/transitive status (`npm ls <pkg>` / `yarn why <pkg>` / `pnpm why <pkg>` / `composer why <pkg>`, or a grep of the lockfile);
- Dependabot PR rows: `gh pr view <n> --json state,mergeable,statusCheckRollup,headRefName`;
- code-scanning rows: open the file at `path:line` and confirm the flagged code is still there;
- the Angular row: read `@angular/core` in `package.json` and the lockfile.

If a spot-check contradicts the report, fix that row yourself and mention it to the user.

### Step 3 — Plan

Build the content of `SECURITY-REMEDIATION.md` (do not write the file yet; Step 4 decides first) from the (spot-checked) Analysis Report, **in the user's language**, following [references/plan-format.md](references/plan-format.md) exactly:

- header with totals by source and severity, and the coverage line (always present, even when every source is `ok`) with the coverage gaps (including "CodeQL does not analyze PHP" when the repo has PHP code);
- blocks ordered by the [block ordering rule](references/plan-format.md#block-ordering-rule) (do not reorder by any other criterion);
- every block with goal, alerts it closes, steps, fix-risk level **and the factors behind it** ([references/risk-model.md](references/risk-model.md)), effort, verification, and who must act;
- a separate block for each Angular major hop ([references/playbooks/angular.md](references/playbooks/angular.md));
- the "Will not be fixed now" section.

Priority and band are copied from the scripts' output. Never recompute or adjust them.

### Step 4 — Report-file decision

Before writing the plan file the **first** time, run the decision in section 7. Then write the file at the repo root.

### Step 5 — Approval

Present a short summary of the plan in the conversation (blocks with fix-risk and effort, plus the path of the file), then ask, in the user's language:

> Which blocks do you approve? You can say "all", "1 and 3", "cancel", or ask for adjustments.

**Stop and wait.** Do not create a branch, run installs, or edit anything until the developer answers. Adjustments → update the plan file and ask again. "Cancel" → stop, and list the files this run created or changed (the plan, `.github-security-remediation.json`, the `.gitignore` line) so the developer can keep or remove them.

### Step 6 — Guided execution (main thread)

Follow [references/execution.md](references/execution.md). In short:

- Ask once whether you may run the project's install and verification commands, and record a baseline before the first block.
- Create a working branch (e.g. `security/remediation-<YYYY-MM-DD>`), confirming the name. **One commit per block.**
- Mechanical changes (lockfile/manifest bumps, overrides, bringing in a green Dependabot PR's change) need no per-file approval once the block is approved.
- Existing Dependabot PRs: never `gh pr merge`. Bring their change into the working branch as that block's commit.
- Application code changes: show the proposed diff and ask before applying, every time.
- Secrets: rotation steps for a human ([references/playbooks/secrets.md](references/playbooks/secrets.md)); resolve as `revoked` only after the human confirms.
- Dismissals: per-alert confirmation with reason and comment ([references/dismissals.md](references/dismissals.md)).
- After each block: verify (build, tests, lint). On failure: stop and propose reverting the block.
- Integration: offer the menu (PR per block, one PR, push the branch only, keep it local). Never push or open a PR without the developer's choice.

Stack playbooks: [npm/yarn/pnpm](references/playbooks/npm.md) · [Angular](references/playbooks/angular.md) · [Composer](references/playbooks/composer.md) · [code scanning](references/playbooks/code-scanning.md) · [secrets](references/playbooks/secrets.md).

### Step 7 — Wrap-up

Re-run `python3 <skill-dir>/scripts/analyze_repo.py` and report, in the user's language:

- alerts **expected to close** (fixed on the branch) against alerts **already closed** on GitHub (dismissed/resolved, or fixed earlier);
- dismissals made (alert, reason, comment);
- what remains and why (no patch, blocked by an upgrade, waiting on a human, out of scope);
- the reminder: alerts fixed on the branch close only after the branch is integrated into the default branch and GitHub re-scans it.

Details in `references/execution.md` (Wrap-up).

## 6. Portfolio mode

The full procedure, permissions and resume guidance are in [references/portfolio.md](references/portfolio.md). Steps:

1. **Preconditions**: confirm the owner list (orgs and/or users, one `--owner` each) or, for a report on specific repositories, the repo list (one `--repo OWNER/NAME` each; for "this repo", take it from `gh repo view --json nameWithOwner`), the host, and the output directory (default `./security-reports`, giving `<out>/<scope>/<YYYY-MM-DD>/`, where `<scope>` is the sorted owner list joined by `+`, or the repos as `owner__name` joined by `+`, and the date is the **UTC** date). Check `gh auth status --hostname <host>`. Explain the fetch strategy (org endpoints vs per-repo "partial view") and, for large owners, the expected duration.
2. **Report-file decision** if the output directory is inside a git repo (section 7).
3. **Run** `python3 <skill-dir>/scripts/run_portfolio.py --owner <o1> [--owner <o2>] --host <host> --out <dir> --lang <code>` (or `--repo <owner/name> [--repo …]` instead of `--owner`). It fetches, snapshots, scores, clusters, diffs against the previous run of the same scope (an earlier run the same day counts; each run is kept in `<day_dir>/runs/` as a trend point), and renders the day folder. Rate-limited or interrupted → re-run the **same command**; finished repos are resumed from the cache.
4. **Narrative**: write `<day_dir>/narrative.txt` in the user's language (key risks, recommended next campaign). Every number must be quoted from `snapshot.json` / `diff.json`; never compute your own.
5. **Re-render** with the narrative: `python3 <skill-dir>/scripts/render_report.py --dir <day_dir> --lang <code> --narrative <day_dir>/narrative.txt`.
6. **Present**: the paths, the contents of `summary.txt`, and the caveats (baseline, partial view, coverage gaps, lost coverage).

Designed for once a day. Re-running on the same UTC day overwrites that day's folder.

## 7. Report-file decision and public-repo warning

Plans and reports list open vulnerabilities. Whether they go into git is the user's decision, asked **once** and remembered.

1. Find the git repo that will contain the file: the current repo (repo mode), or `git -C <out-dir-parent> rev-parse --show-toplevel` for the portfolio output directory. Not inside a git repo → nothing to decide.
2. Get that repo's visibility: `gh repo view --json visibility --jq .visibility`, run from `<repo-root>` (no GitHub remote → treat it as PRIVATE).
3. Read `<repo-root>/.github-security-remediation.json`. If it holds `{"commit_reports": true|false}`, apply it without asking. One exception: in portfolio mode, a stored `true` in a PUBLIC or INTERNAL repo was possibly chosen for a single repo plan, while an org-wide report discloses much more. Re-confirm it once, with the warning below, before writing the report there.
4. Otherwise ask, in the user's language: *"Should `<file or folder>` be versioned in git, or added to `.gitignore`?"*
   - **PUBLIC repo**: strongly recommend `.gitignore`, and say why: a committed plan or report publicly lists the repo's (or the org's) open vulnerabilities, affected files and secret types, while the Security tab itself is only visible to people with access. Anyone could use it to pick targets.
   - **INTERNAL repo**: recommend `.gitignore` (every member of the enterprise can read it).
   - **PRIVATE repo**: either is fine; let the user choose.
5. Write `<repo-root>/.github-security-remediation.json` with exactly `{"commit_reports": <bool>}`. The file holds no findings.
6. If `commit_reports` is `false`, append the path to `<repo-root>/.gitignore` when it is not already there: `SECURITY-REMEDIATION.md` (repo mode) or the output directory relative to the repo root, e.g. `security-reports/` (portfolio mode). If it is `true` in portfolio mode, still add `<out>/**/.cache/` (the partial-run cache), with `<out>` relative to the repo root.
7. If the user insists on versioning in a public repo, respect it and record it, after stating the warning once more.

These edits (`.gitignore`, the config file) are the skill's own setup. In repo mode they go into the first commit on the working branch (see `references/execution.md`).

## 8. Golden rules

- Never print, store, or send secret values. Always use `hide_secret=true`.
- Never modify application code without explicit approval. Never push, open PRs, or merge without the developer's choice.
- Never dismiss an alert without per-alert confirmation and a justification.
- Never run `git reset --hard`, `git clean`, or force-push. Never install global tools without asking.
- Never send data to external services. The HTML report makes zero network requests.
- Never treat missing coverage as zero alerts.
- Dirty working tree at start: stop and ask.

Applied to this skill:

- Never run `gh pr merge`. Never write `Closes #N` / `Fixes #N` for alert numbers in commits or PRs (GitHub would close the issue or PR with that number).
- Never read `.env*` files or print anything that looks like a credential. Secret alerts are handled by type, path and line only; secret-bearing lines (secret-scanning locations and the lines of code-scanning credential alerts, `credential_rule: true`) are viewed, edited and diffed only through `secret_redact.py`, never with the Read/Edit tools, `cat`, `git diff`, `git show` or `git log -p`.
- Never call `dismiss.py` (or any PATCH/POST) from the subagent, or without the developer's confirmation of that exact alert.
- Priority, bands, totals and deltas come only from the scripts. You never estimate them.
