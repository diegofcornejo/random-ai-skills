# Portfolio Mode

One run produces **one combined, consolidated report** for every requested owner (orgs and/or user accounts), with the change since the previous report of the same scope. It is designed to run once a day and hand to the client's security team. It is read-only on GitHub.

Everything the user reads (questions, the narrative, the report via `--lang`, your summary) is in **the user's language**.

## 1. Preconditions

1. **Owners**: confirm the exact list, e.g. `acme-telco` and `acme-mobile`. Each is an org or a user login; each becomes one `--owner`. Ask if the request is vague ("all our orgs"). Logins are case-insensitive: the scripts replace what was typed with GitHub's spelling of the login (`Acme-Telco` → `acme-telco`) everywhere in the report, and a change of case alone never starts a new baseline.
2. **Host**: `github.com` by default. For GitHub Enterprise Cloud with data residency (`<name>.ghe.com`) or GitHub Enterprise Server, ask for the hostname and pass `--host`.
3. **Auth**: `gh auth status --hostname <host>`. Not logged in → ask the user to run `gh auth login --hostname <host>`. Private repos' code and secret scanning need the `security_events` scope (classic tokens): `gh auth refresh -s security_events`, run by the user.
4. **Output directory**: default `./security-reports`. The day folder is `<out>/<scope>/<YYYY-MM-DD>/`:
   - `<scope>` is the owner list, lower-cased, sorted and joined with `+` (`acme-mobile+acme-telco`, or a username);
   - the date is the **UTC date** of the run, not the local date. Near midnight it can differ from the user's calendar day; say so if it matters.
5. **Archived repos** are excluded by default. Add `--include-archived` only if the user asks.
6. **Report-file decision**: if the output directory is inside a git repo, run SKILL.md section 7 for that folder (with the public-repo warning: a committed report lists every repo's open vulnerabilities).
7. **First run** for this scope (no earlier day folder under `<out>/<scope>/`): show the first-run notice (SKILL.md section 1).

## 2. Permissions and fetch strategy (explain before running)

The script picks the strategy per owner by itself. Tell the user which one to expect and what it means:

| Owner | Operator | Strategy | Cost | What the report says |
|-------|----------|----------|------|----------------------|
| Org | Org **owner** or **security manager** | **Org endpoints** (`/orgs/{org}/…/alerts`): a few paginated calls per source | Minutes | Strategy "org endpoints"; full view |
| Org | Regular member (org endpoints answer 403/404) | **Per-repo fallback**: lists the repos the operator can access and calls the per-repo endpoints | About 3+ calls per repo: 500 repos ≈ 1,500–2,000 calls, within the 5,000/hour authenticated limit | **"Partial view: only repositories and alerts visible to `<user>`"**; repos whose alerts the user cannot read appear under coverage as `no_permission` |
| User account (your own login) | You | Per-repo, always. Repos are listed with `GET /user/repos?affiliation=owner&visibility=all`, so your private repos are included | Same as above | Same partial-view label |
| User account (someone else) | Anyone | Per-repo, always. GitHub lists only that account's **public** repos | Same as above | Same partial-view label, plus **"public repositories only"** |

Coverage per repo and source is one of `ok`, `not_enabled`, `not_licensed`, `no_permission`, `unavailable`. **Only `ok` counts**; a repo with no `ok` source is "without coverage", never "zero alerts", and can never "reach zero". A repo is **at zero** (`totals.repos.zero_open`) or **reaches zero** (`diff.repos_reached_zero`) only when **all three** sources are `ok`. A repo with 0 open alerts but a scanner missing is listed separately as "0 open in covered scanners (partial coverage)" (`zero_open_partial`, `repos_reached_zero_partial`); never call it clean or at zero. When you explain `not_enabled` on a **private** repo, say that it can mean the paid product (GitHub Code Security or Secret Protection) is simply not turned on for that repo, and that the action is "enable it (requires license seats)". `not_licensed` means the organization has no license for it. On the org endpoints, a repo with no Dependabot alerts is probed with `GET /repos/{o}/{r}/vulnerability-alerts`; its 404 means `not_enabled` only when the operator is an org **owner** (checked once per org with `GET /user/memberships/orgs/{org}`). For anyone else, a security manager included, it is `unavailable`: unknown, not "disabled".

## 3. Run

```bash
python3 <skill-dir>/scripts/run_portfolio.py --owner <owner1> [--owner <owner2> …] \
  --host <host> --out <out-dir> --lang <code>
```

- It fetches every owner, writes one combined `snapshot.json` (secret-free, deterministic), scores and clusters, diffs against the most recent earlier snapshot of the **same scope** (`diff.json`), and renders `report.html` and `summary.txt`.
- On success it prints JSON with the paths: `day_dir`, `snapshot`, `diff`, `report`, `summary`.
- Re-running on the **same UTC day overwrites** that day's folder. That is expected: the latest run of the day is the day's report.
- Large owners take time. In Claude Code, run it with `run_in_background` and wait for it to finish, or give the user the command to run in their own terminal. Progress and rate-limit messages go to stderr.

### Rate limits and resume

- The script backs off by itself on rate limits (primary and secondary): it waits 60 s, then doubles (up to 15 min per wait), up to 5 retries, printing `rate limited on …; retrying in Ns` to stderr.
- If it still fails, it exits with `{"error": …, "hint": …}`. Each repo already fetched is kept in `<day_dir>/.cache/`.
- **To resume, re-run the same command.** Cached repos are skipped and never counted twice; only the missing ones are fetched. Each owner's fetch strategy (and the reason for a per-repo fallback) is cached too, so a resumed run keeps the strategy of the interrupted one, including its "partial view" label. The cache is deleted after a successful run.
- If the retry happens after UTC midnight, add `--date <YYYY-MM-DD of the interrupted run>` (zero-padded, e.g. `2026-01-05`; anything else is refused) to resume into the same folder. With `--date`, `generated_at` becomes `<date>T09:00:00Z`.
- Never "fix" a rate-limit failure by fetching fewer repos and presenting the result as complete.

## 4. Narrative

After the run, write a short narrative (key risks, recommended next campaign) **in the user's language** to `<day_dir>/narrative.txt`: plain text, 2–4 short paragraphs separated by blank lines, no Markdown. It goes into the report's executive summary.

Read the numbers you may quote with this read-only extraction (it prints only aggregates, so it stays small for 500 repos):

```bash
python3 - "<day_dir>" <<'PY'
import json, sys
from pathlib import Path
day = Path(sys.argv[1])
s = json.loads((day / "snapshot.json").read_text())
d = json.loads((day / "diff.json").read_text())
t = s["totals"]
facts = {
    "scope": s["scope"], "generated_at": s["generated_at"],
    "open": t["open"], "by_source": t["by_source"], "by_severity": t["by_severity"],
    "by_band": t["by_band"], "by_owner": t["by_owner"],
    "repos_total": t["repos"]["total"], "repos_scanned": t["repos"]["scanned"],
    "repos_no_coverage": len(t["repos"]["no_coverage"]), "repos_zero_open": len(t["repos"]["zero_open"]),
    "repos_zero_open_partial": len(t["repos"]["zero_open_partial"]),
    "baseline": d["baseline"], "baseline_reason": d["reason"], "diff_totals": d["totals"],
    "closed": len(d["closed"]), "new": len(d["new"]), "dismissed": len(d["dismissed"]),
    "repos_reached_zero": d["repos_reached_zero"][:10],
    "repos_reached_zero_partial": d["repos_reached_zero_partial"][:10],
    "cluster_moves": d["clusters"][:10],
    "top_clusters": sorted(s["clusters"], key=lambda c: (-c["repos"], -c["alerts"], c["key"]))[:5],
    "top_repos": s["ranking"][:5],
    "waves": [{"wave": w["wave"], "alerts": len(w["alerts"]), "repos": len(w["repos"])} for w in s["waves"]],
}
print(json.dumps(facts, indent=1, sort_keys=True))
PY
```

### Narrative rules

- **Numbers only from `snapshot.json` / `diff.json`** (the extraction above, or the files themselves). Quote them; never compute your own: no sums, differences, percentages or averages that the files do not contain. If a number you want is not there, leave it out.
- **Baseline** (`diff.baseline` is `true`): say it is a baseline (`first_run`, `owner_set_changed`, or `previous_unreadable`: the previous day's `snapshot.json` could not be read) and do not claim any progress or regression.
- **Delta and lost coverage**: `diff_totals.delta` is `curr_open − prev_open`. Alerts in `lost_coverage` disappeared because their repo/source **lost coverage**; they are **not closures** and must not be presented as progress. Whenever `diff_totals.lost_coverage` is above 0, say so next to the delta.
- **Coverage**: mention repos without coverage as unknown, never as clean. Repos in `repos_zero_open_partial` / `repos_reached_zero_partial` have 0 open alerts only in the scanners that are readable: say "partial coverage", never "at zero".
- **Campaigns** ("fix once, close many"): recommend the next one from `top_clusters` (key, repos, alerts, `fix`), or wave 1 when there are open secrets or P1s. Call a campaign **completed only when its `curr_open` in `cluster_moves` is 0**; a cluster that shrank (or dropped below 2 repos) is progress, not completion. `curr_open` already counts the cluster's alerts hidden by lost coverage (the entry's `lost_coverage`): their state is unknown, so a cluster with `lost_coverage` above 0 is never completed. Say how many are hidden.
- **Repo names are always owner-qualified** (`acme-telco/billing-api`), also when there is a single owner.
- **Partial view**: if any owner's `scope.strategy` is `per-repo`, say that the figures cover only what the operator can see. If an owner is in `scope.public_only` (another person's user account), say that only its public repositories are included.
- Write for a security lead: risks first, then the recommendation. No marketing tone, no secret values, no alert details beyond what the report already shows.

## 5. Re-render with the narrative

```bash
python3 <skill-dir>/scripts/render_report.py --dir <day_dir> --lang <code> --narrative <day_dir>/narrative.txt
```

It rewrites `report.html` (now with the narrative in the executive summary) and `summary.txt`, and prints `{"report", "summary", "lang"}`. `summary.txt` stays fully script-generated. If `lang` in the output is not the code you passed, the template fell back to English: tell the user.

Always rewrite `narrative.txt` after each run of the day, so a stale narrative never sits next to new numbers.

## 6. Present

In the user's language:

1. The day folder and its files: `report.html` (self-contained, zero network requests, print to PDF from the browser), `summary.txt`, `snapshot.json`, `diff.json`, `narrative.txt`. The report's sections: executive summary (totals, day delta, per-owner table, your narrative), trend over the available snapshots, coverage per repo, top-risk repos, "fix once, close many" campaigns, remediation waves, dismissals audit (who, what, reason, comment), and methodology (how scores and counts are computed).
2. The contents of `summary.txt`, verbatim, ready to paste into Teams, Slack or email.
3. The caveats that apply: baseline, partial view, repos without coverage, lost coverage.
4. Daily use: run the same request tomorrow; the diff compares with the latest earlier day of the same owner set. Changing the owner set starts a new baseline.
