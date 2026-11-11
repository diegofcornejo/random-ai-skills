# github-security-remediation

Turns the alerts in a GitHub **Security** tab (Dependabot, code scanning, secret scanning) into a remediation plan you can act on, and into a daily progress report for a security team. It ships as a Claude Code plugin: this skill plus a read-only analysis subagent, `security-alerts-analyzer`.

This README is in English, like everything in the repo. The skill itself answers in the language you write to it: conversation, questions, the plan file, dismissal comments and the report (English and Spanish templates in v1; other languages get an English report and a conversation in your language).

Contents: [What it is](#1-what-it-is-and-what-it-is-not) · [Quick start](#2-quick-start) · [Requirements](#3-requirements-and-permissions) · [What you get](#4-what-you-get) · [On its own vs asks first](#5-what-it-does-on-its-own-and-what-it-asks-first) · [Safety](#6-safety-and-privacy) · [Numbers](#7-how-the-numbers-are-computed) · [Daily usage](#8-daily-usage) · [Limitations and FAQ](#9-limitations-and-faq)

## 1. What it is and what it is not

It has two modes, picked from your request:

- **Repo mode.** You open a repository and ask for a plan. It reads that repo's open alerts, checks the manifests and lockfiles, and writes `SECURITY-REMEDIATION.md`. The plan groups the alerts into blocks, and each block states its priority, fix-risk, effort, and who must act. Then it carries out the blocks you approve, on a working branch, one commit per block, asking you before any change to application code.
- **Portfolio mode.** You name one or more orgs or user accounts, or specific repositories. It produces one consolidated report folder per day: an HTML report, a paste-able summary, and JSON data, with the change since the previous day.

What it is not:

| It is not… | In practice |
|---|---|
| A scanner | It reads the alerts GitHub already has. It runs no vulnerability scanning of its own. |
| A secret rotator | It tells you what to rotate and in what order. A person rotates the credential at the provider (cloud console, vault, CI secrets). |
| A merge bot | It never merges anything. You decide how and when the work reaches the default branch. |
| A hosted service | Apart from the GitHub actions you approve (dismissals, push, PRs), it only writes local files, and it sends your alert data to no other service. |
| A replacement for GitHub Security Overview | It adds prioritization, cross-repo campaigns, plans and day-over-day tracking on top of the same data. |

## 2. Quick start

### Install

**Claude Code plugin (recommended).** You get the skill and the subagent together:

```text
/plugin marketplace add diegofcornejo/random-ai-skills
/plugin install github-security-remediation@random-ai-skills
```

Or in one step (Claude Code ≥ 2.1.275): `/plugin install github-security-remediation --marketplace diegofcornejo/random-ai-skills`.

In a plugin install the subagent is namespaced as `github-security-remediation:security-alerts-analyzer`.

**`npx skills` (skill only).** This works for Claude Code and any agent that supports the skills format:

```bash
npx skills add https://github.com/diegofcornejo/random-ai-skills --skill github-security-remediation
```

`npx skills` does not install subagents. For Claude Code, add it from a clone of the repo:

```bash
git clone https://github.com/diegofcornejo/random-ai-skills ~/random-ai-skills
~/random-ai-skills/scripts/install-agents.sh --claude
```

This links every subagent in the repo (`agents/*.md`) into `~/.claude/agents/`, not only `security-alerts-analyzer`. Without the subagent the skill still works. It runs the same analysis inline, in your conversation, so it uses more of your context.

Pick one channel. Installing through both gives you duplicates.

### Prompts to copy

| Goal | Prompt |
|---|---|
| Plan and fix the current repo | *Use github-security-remediation to plan and fix this repo's security alerts* |
| Today's report for an org | *Use github-security-remediation to generate today's security report for org acme-telco* |
| Plan only, change nothing | *Use github-security-remediation to plan this repo's security alerts. Only the plan, no changes.* |
| Daily HTML report for one repo | *Use github-security-remediation to generate today's HTML security report for this repo only* |
| Several owners in one report | *Use github-security-remediation to generate today's security report for acme-telco and acme-mobile* |
| Same thing, in Spanish | *Usa github-security-remediation para generar el reporte de seguridad de hoy para la org acme-telco* |

Run repo mode from inside the repository's working copy. If a request could mean either mode (for example "security report" inside a repo with no owner named), the skill asks which one you mean.

The first time it runs in a repo or for a report scope, it tells you in a few lines what it will produce and what it will ask you before acting.

## 3. Requirements and permissions

| Requirement | Details |
|---|---|
| `gh` CLI | Installed and logged in: `gh auth login --hostname <host>`. Every GitHub call goes through it, with your own account. The skill stores no tokens. |
| Token scope | Code scanning and secret scanning alerts on private repos need `security_events` (classic tokens): `gh auth refresh -s security_events`. You run it yourself; the skill asks you to. |
| Python | 3.9 or newer. Standard library only, nothing to `pip install`. |
| git | Repo mode works in a git working copy with a clean tree. If the tree is dirty, it stops and asks you to commit or stash first. |
| Hosts | github.com, GitHub Enterprise Cloud (including data residency `*.ghe.com`), and GitHub Enterprise Server. The host comes from the repo's remote, or you name it. On older Enterprise Server versions, missing features (EPSS, org endpoints, Autofix) are skipped, not treated as errors. |
| Stacks with specific guidance | Angular, JavaScript/TypeScript with npm, yarn or pnpm, and PHP with Composer. Other ecosystems still appear in the plan, with generic guidance only. |

### Which permissions unlock what

| Your role | Without paid GitHub security products | With GitHub Code Security / Secret Protection (Advanced Security) |
|---|---|---|
| **Regular user** (personal account, collaborator, org member) | Dependabot alerts on the repos you can read alerts for. Code scanning and secret scanning on public repos, where GitHub offers them for free. Portfolio mode uses the per-repo path and the report is labelled **partial view**. Private repos without the products show their coverage as `not_enabled` or `not_licensed`. | Same per-repo path, plus code scanning and secret scanning on the private repos where the products are turned on and your role can read the alerts. Anything your role cannot read shows as `no_permission`. |
| **Org owner or security manager** | Portfolio mode uses the org endpoints: a few paginated calls per source, full view of the org. Private repos without the products show coverage as `not_enabled` or `not_licensed`. | Org endpoints for all three sources: the complete picture of the org. |

- Reading secret scanning alerts usually needs repo admin, org owner or security manager. Without it, secret scanning shows as `no_permission` for that repo.
- As a security manager (not an org owner), repos with no Dependabot alerts may show Dependabot as `unavailable`: GitHub's Dependabot status check needs admin rights, so the skill does not guess "not enabled" from its 404.
- A user account (not an org) is always fetched repo by repo. For your own account (the one `gh` is logged in as) every repo you own is included, private ones too. For someone else's user account GitHub lists only its public repositories, and the report says "public repositories only" for that owner.
- Dismissing an alert needs permission to dismiss on that repo. If GitHub refuses (HTTP 403), the skill stops and tells you. It does not try another way.
- Portfolio mode only reads. It changes nothing on GitHub.

## 4. What you get

### Repo mode

| File or change | What it is |
|---|---|
| `SECURITY-REMEDIATION.md` at the repo root | The plan, in your language: header with totals by source and severity, coverage gaps, numbered blocks, a "Will not be fixed now" table, and the approval question. Before writing it the first time, the skill asks whether to version it or add it to `.gitignore`. |
| `.github-security-remediation.json` | Your answer to that question, `{"commit_reports": true}` or `false`, so it is not asked again. It holds no findings. |
| A working branch, e.g. `security/remediation-2026-11-10` | Created only after you approve blocks, with the name confirmed with you. One commit per block. |
| A wrap-up in the conversation | Alerts expected to close, alerts already closed, dismissals made, and what remains and why. |

Each block in the plan has: goal, alerts it closes (linked), priority, steps, fix-risk level with the concrete factors behind it, effort (S/M/L), verification commands, who acts (agent, developer, or a human outside the repo), and dependencies. An exposed secret is always block 1. Every Angular major hop (11→12, 12→13, …) is its own block, never mixed with routine bumps.

Excerpt from the [example plan](examples/SECURITY-REMEDIATION.example.md) ([Spanish version](examples/SECURITY-REMEDIATION.example.es.md)), built from synthetic data for a fictional org:

```markdown
| # | Block | Closes | Priority | Fix-risk | Effort | Who acts |
|---|-------|--------|----------|----------|--------|----------|
| 1 | Bring in Dependabot PR #7 (lodash 4.17.21) | 1 alert | P1 | low | S | Agent |
| 2 | Angular framework patch 11.0.0 → 11.0.5 | 1 alert | P1 | low | S | Agent |
| 3 | Fix client-side XSS in `src/app/render.ts` | 1 alert | P2 | low | S | Agent prepares, developer approves |
| 4 | karma 5.1 → 6.3.16 (major upgrade of the test runner) | 1 alert | P3 | high | M | Agent, developer |
| 5 | Dismissal candidate: karma (alternative to block 4) | 1 alert | P3 | low | S | Developer confirms, agent runs it |

### Block 4 — karma 5.1 → 6.3.16 (major upgrade of the test runner)
- **Fix-risk:** high
  - major jump of karma itself, 5.1 → 6.3.16
  - direct `development` dependency: nothing in the production build changes
  - `karma.conf.js` may need changes (a config file)
  …
```

In that repo the Angular alert is fixed by a patch inside major 11, so its plan has no Angular major hop. The example ends with a clearly labelled, hypothetical appendix that shows what an Angular major-upgrade block (11 → 12) looks like when an alert does need one.

### Portfolio mode

One folder per day, per scope:

```text
security-reports/                 # default output directory (configurable)
  acme-telco/                     # scope: the owners, lower-cased, sorted, joined with "+" (e.g. acme-mobile+acme-telco)
    2026-11-10/
    2026-11-11/                   # UTC date of the run
  acme-telco__portal-web/         # scope of a single-repo report (--repo acme-telco/portal-web)
      report.html                 # self-contained report, printable to PDF from the browser
      summary.txt                 # 5–10 lines to paste into Teams, Slack or email
      snapshot.json               # normalized, secret-free alert data: the source of every number
      diff.json                   # change against the previous day of the same scope
      narrative.txt               # the analyst notes the agent wrote for the report, in your language
      .cache/                     # transient: exists only during a run, or after an interrupted one (for resume)
```

`report.html` sections: 1. Executive summary (totals, day delta, per-owner table, analyst notes) · 2. Trend · 3. Coverage per repo · 4. Top-risk repositories · 5. "Fix once, close many" campaigns (across repos; in a single-repo report, one row per package upgrade that closes several of its alerts) · 6. Remediation waves · 7. Dismissals audit (who, what, reason, comment) · 8. Methodology.

Examples generated by the real scripts from synthetic data (fictional org `acme-telco`, two days): [report.en.html](examples/report.en.html) · [report.es.html](examples/report.es.html) · [summary.en.txt](examples/summary.en.txt) · [summary.es.txt](examples/summary.es.txt). GitHub shows `.html` files as source: download the file and open it in a browser. It makes no network requests.

`summary.en.txt` from that example:

```text
GitHub security report: acme-telco (2026-11-11)
Open alerts: 6 (-1 vs. previous report; hidden by lost coverage, not fixed: 0)
Since the previous report: 2 closed (1 dismissed), 1 new
By priority: P1 3, P2 3, P3 0
Coverage: 3 of 5 repositories scanned; 2 without any readable scanner (not counted as zero)
Top risk: acme-telco/billing-api (priority 85); acme-telco/portal-web (priority 75)
Wave 1 (do now): 3 alerts in 2 repositories
Reached zero open alerts: acme-telco/shared-ui
Full report with details per repository, waves and methodology: report.html
```

## 5. What it does on its own and what it asks first

| Action | On its own? | Details |
|---|---|---|
| Read alerts | Yes | GET calls through your `gh` login. Secret scanning is always fetched with `hide_secret=true`. |
| Analyze repo files | Yes, read-only | Manifests, lockfiles, `angular.json`, `composer.json`, the flagged code lines. Never `.env*` files. The subagent has no Edit or Write tools. It does have a shell, and its instructions forbid installs, commits, dismissals and any non-GET API call; every write happens in the main conversation, after your approval. |
| Write the plan file | Asks once | First it asks whether to version the plan or add it to `.gitignore`, then remembers the answer. |
| Run installs, builds and tests | Asks once | Before the first block it asks whether it may run `npm ci`, `ng build`, `ng test`, `composer test`, and so on. If you say no, it lists the commands for you to run. `ng update` is asked before every Angular hop. |
| Mechanical bumps | Yes, after you approve the block | Lockfile and manifest bumps, `overrides` / `resolutions`, `composer update <pkg> --with-dependencies`. No per-file approval. It shows `git diff --stat` before committing. |
| Dependabot PR changes | Yes, after you approve the block | The PR's change is brought into the working branch as that block's commit (cherry-pick, or the same bump redone if the PR is stale). The PR is never merged with `gh pr merge`. GitHub closes it as superseded once you integrate the branch. |
| Application code changes | Asks first, every time | Code-scanning fixes, API changes after upgrades, Angular migration edits: shown as a diff, applied only if you approve. |
| Dismissals | Asks first, per alert | Each one is proposed with GitHub's reason and a comment of at most 280 characters, then confirmed by you for that exact alert, dry-run first. "Dismiss all" without seeing each one does not count. |
| Secrets | Never rotates | A person rotates the credential at the provider and updates its consumers. Removing the value from code is a code change, approved on a description with the value masked. The alert is resolved as `revoked` only after you confirm the rotation. |
| Commits | Yes, on its working branch | One commit per block, staged by explicit path, Conventional Commits by default. Never `git reset --hard`, `git clean`, or history rewrites. |
| Push and PRs | Asks first | You choose: one PR per block, one PR, push the branch only, or keep it local. Never merges and never force-pushes. |
| Anything on GitHub in portfolio mode | Never | Portfolio mode is read-only. |

After a failed build or test, it stops and proposes reverting that block (`git restore` before the commit, `git revert` after).

The only limit enforced by tooling is that the subagent has no Edit or Write tools. Everything else in this table is a rule the skill and the subagent are instructed to follow. Claude Code's own permission prompts still apply on top of those rules.

## 6. Safety and privacy

- **Secrets are never stored or shown.** Alerts are fetched with `hide_secret=true`, and the scripts strip any `secret` field again before anything is written. Snapshots, reports and plans keep only the secret type, validity, public-leak and push-protection flags, and the file locations.
- **Secret-bearing lines are only handled masked.** A helper script shows those lines with the secret replaced by `[redacted]` (or the whole line redacted), replaces them without printing them, and checks the change by structure only. It refuses a location that changed since GitHub reported it, so it never edits the wrong line. The skill's rules forbid opening those lines with the normal file tools, `cat` or `git diff`. The same applies to code-scanning alerts about credentials (for example CodeQL's hard-coded credentials rule), because they point at the line that holds the credential.
- **No external requests.** The HTML report is one self-contained file: inline CSS and SVG, no scripts, no fonts or CDNs, and the only links point to your GitHub host. Alert data and findings go nowhere: GitHub is reached only through `gh`, with your account. Package installs you allow (`npm ci`, `ng update`, `composer update`) reach your package registry as they always do. For an Angular major hop, the agent may read the public Angular update guide, sending only version numbers.
- **Public-repo warning.** A plan or report lists open vulnerabilities. Before writing one into a git repo, the skill asks whether to version it. In a public repo it strongly recommends `.gitignore`, because a committed plan would publicly list targets that the Security tab only shows to people with access. In an internal repo it recommends `.gitignore` too.
- **Dismissal audit trail.** Dismissals are made with your own account, so GitHub records who did it. Each one carries a reason and a justification comment, and the daily report's **Dismissals audit** section lists who dismissed what, with which reason and comment.
- **Commits and PRs** never contain secret values. A PR body lists only what that PR fixes, never the alerts still open. Alerts are referenced by URL, never as `#N` (GitHub would close the issue or PR with that number).

## 7. How the numbers are computed

Every number comes from scripts reading GitHub API data. The model never estimates, rounds or recomputes them: it writes the analysis and the recommendations on top.

There are two separate axes, never blended:

| Axis | Question | Computed by |
|---|---|---|
| **Priority** (0–100, band P1/P2/P3) | How urgent is the vulnerability? | `score.py`, deterministically. Drives block order, waves and top-risk repos. |
| **Fix-risk** (low/medium/high) | What does applying the fix imply? | The agent, with a fixed rubric (semver jump, direct vs transitive, Angular major hops, files to change, tests available, PHP platform, secret consumers). Shown with its factors on every block. |

Priority in brief: a severity base (critical 40, high 30, medium 20, low 10), or 60 for an exposed secret (+25 if still active, +15 if publicly leaked, +10 if push protection was bypassed); EPSS percentile ≥50 +5, ≥80 +15, ≥95 +25; runtime +10 or development −10; direct dependency +5; −15 for code in tests or generated files; +10 or +5 for repos pushed in the last 30 or 180 days. Clamped to 0–100. P1 ≥ 70, P2 ≥ 40, P3 below.

- Full rules: [references/risk-model.md](references/risk-model.md).
- The same weights are printed in each report's **Methodology** section and stored in `snapshot.json` under `methodology`, so every score can be checked by hand.
- Output is deterministic: the same GitHub data gives the same numbers, byte for byte.

## 8. Daily usage

- Run portfolio mode once a day with the same prompt (or the same owners). The day folder is named by the **UTC** date, so near midnight it can differ from your calendar day.
- Re-running on the same UTC day overwrites that day's folder. The latest run of the day is the day's report.
- **The delta** compares with the most recent earlier day folder of the same scope. `delta` is today's open alerts minus the previous report's.
- **Baseline.** The first report for a scope, a report whose owner set changed, or one whose previous `snapshot.json` cannot be read (for example, truncated by a crash), is a baseline. It says so and shows no delta, and the next day compares normally again.
- **When fixes show up.** Alerts close only on the default branch: Dependabot when the default branch's manifest or lockfile has the fixed version, code scanning when an analysis of the default branch no longer finds the issue. Secret scanning alerts never close by themselves: someone rotates the credential and resolves the alert. Work still on a branch, or merged but not yet rescanned, leaves the alerts open, so ask for the report after the merge and the scan finish.
- **Lost coverage is not progress.** If an alert disappears because its repo lost scanner coverage (a scanner was turned off, a permission changed), it is not counted as closed. The report shows it as "hidden by lost coverage" next to the delta.
- **Large orgs and resume.** The per-repo path costs about 3 or more calls per repo (500 repos is roughly 1,500–2,000 calls, within GitHub's 5,000 per hour). The script paces itself and backs off on rate limits (60 s, doubling up to 15 min, up to 5 retries). If it still stops, ask again or re-run the same command: finished repos are taken from `.cache/` and never counted twice, and each owner keeps the fetch strategy (and "partial view" label) of the interrupted run. If the retry happens after UTC midnight, the agent passes `--date <day of the interrupted run>` to resume into the same folder.
- **Without the agent** (for example from a scheduler): `python3 <skill-dir>/scripts/run_portfolio.py --owner acme-telco --lang en` (or `--repo acme-telco/portal-web` for one repo), where `<skill-dir>` is the folder holding this skill's `SKILL.md`. The output is the same, minus the analyst notes.

## 9. Limitations and FAQ

**Why does a repo with no alerts not count as "zero"?** Coverage is tracked per repo and per source: `ok`, `not_enabled`, `not_licensed`, `no_permission`, `unavailable`. Only `ok` counts. A repo with no `ok` source is "without coverage": its alerts are unknown, never zero, and it can never "reach zero". A repo counts as "at zero", or "reached zero", only when all three scanners are readable. A repo with 0 open alerts but a scanner missing (for example, code scanning not enabled on a private repo) is listed separately as "0 open in covered scanners (partial coverage)".

**What does `not_enabled` mean on a private repo?** The scanner is turned off for that repo. On a private repo this can mean the paid product (GitHub Code Security or Secret Protection) is simply not turned on for it, even if the org has seats. The action is to enable it in the repo's security settings, which requires available license seats. `not_licensed` means GitHub says the org has no license for that feature.

**Why is PHP code not covered by code scanning?** CodeQL does not analyze PHP. In a PHP repo, Dependabot covers Composer dependencies, but the PHP code itself has no code-scanning coverage. The plan says so in its coverage gaps.

**Why does the report say "partial view"?** When the org endpoints are not available to you (you are not an org owner or security manager), or the owner is a user account, the report covers only the repositories and alerts your account can see. Repos whose alerts you cannot read appear under coverage as `no_permission`. For another person's user account, only its public repositories are listed at all, and the report labels that owner "public repositories only".

**How long does a large org take?** Org endpoints take minutes. The per-repo path for hundreds of repos can take much longer and can hit rate limits. In Claude Code the agent runs it in the background, or gives you the command to run in your own terminal.

**When do fixed alerts close?** Alerts fixed on the working branch close only after the branch is integrated into the default branch and GitHub re-evaluates it. A secret-scanning alert closes only when it is resolved, never just because the secret left the code.

**Which stacks are covered?** v1 has specific playbooks for Angular, JavaScript/TypeScript (npm, yarn, pnpm) and PHP (Composer). Other ecosystems (Maven, pip, Go, …) appear in the plan with generic guidance only.

**Other limits in v1**

- Report templates exist in English and Spanish. For other languages the report falls back to English, and the skill tells you.
- The subagent exists for Claude Code only. Other agents run the analysis inline.
- Copilot Autofix suggestions appear only where GitHub's Autofix endpoint answers.
- With `core.autocrlf=true` (common on Windows), secret locations read as changed, so the masked edit is refused and you make that edit yourself. A shallow clone may need `git fetch` before a secret location can be checked.
