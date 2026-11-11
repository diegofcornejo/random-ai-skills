# Repo Analysis Protocol

Canonical, **read-only** analysis protocol for `github-security-remediation`. Two callers use it:

- the `github-security-remediation` **skill**, when it runs the analysis inline;
- the `security-alerts-analyzer` **subagent**, when the skill delegates to keep the main context clean.

Both must return the same **Analysis Report** (end of this file). The skill builds `SECURITY-REMEDIATION.md` from it.

> This protocol never edits, writes, installs, commits, pushes, dismisses, or calls any API other than GET. It never runs `dismiss.py`, `npm install`, `composer update`, `ng update`, or `gh pr merge`. If you are tempted to fix something, record it in the report instead.

## Inputs

From the task prompt (or, inline, from the skill's Step 1): the skill dir (`<skill-dir>`), the project root, `owner/name`, the host, visibility, default branch and working-tree state. Run every command from the project root. Scripts are at `<skill-dir>/scripts/`.

## Phase 1 — Fetch the alerts

Run the analysis CLI and keep only what you need. The filter prints the repo-level context, then one compact line per **open** alert:

```bash
python3 <skill-dir>/scripts/analyze_repo.py --repo <owner/name> --host <host> 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "error" in d:
    print(json.dumps(d)); sys.exit(2)
print(json.dumps({k: d.get(k) for k in ("scope", "repo_meta", "coverage", "totals", "autofix", "dependabot_prs")}, indent=1, sort_keys=True))
keep = ("source", "number", "severity", "priority", "band", "ecosystem", "package", "manifest", "scope",
        "relationship", "advisory", "cve", "epss_percentile", "first_patched", "vulnerable_range", "rule_id",
        "rule_description", "tool", "path", "start_line", "end_line", "start_column", "end_column", "commit_sha",
        "credential_rule", "classifications", "secret_type", "validity", "publicly_leaked",
        "push_protection_bypassed", "html_url")
print("OPEN ALERTS")
for a in d["alerts"]:
    if a["state"] == "open":
        print(json.dumps({k: a[k] for k in keep if a.get(k) not in (None, "", [])}, sort_keys=True))
'
```

- `--repo`/`--host` may be omitted inside a checkout: the CLI detects them with `gh repo view`.
- On `{"error": …, "hint": …}`: stop, and return a report with only the header lines you know plus the error and hint under **Notes**. Do not retry with hand-written `gh api` calls.
- What the CLI gives you:
  - `coverage[0]`: `dependabot`, `code_scanning`, `secret_scanning`, each one of `ok`, `not_enabled`, `not_licensed`, `no_permission`, `unavailable`. Only `ok` means "the alerts were read". Anything else is **no coverage**, never zero alerts.
  - `totals`: open counts `by_source`, `by_severity`, `by_band`, plus `closed_known` (dismissed/resolved alerts already on GitHub).
  - `priority` (0–100) and `band` (P1/P2/P3) per alert, computed by `score.py`. Copy them. Never recompute them.
  - `dependabot_prs`: open PRs by `app/dependabot` with `number`, `title`, `headRefName`, `url`, `mergeable`, `statusCheckRollup`.
  - `repo_meta`: `private`, `default_branch`, `pushed_at`.
  - `autofix`: code-scanning alert number → Autofix status, or `unavailable`.
- Secret-scanning alerts carry `secret_type`, `validity`, `publicly_leaked`, `push_protection_bypassed`. The secret value is never fetched (`hide_secret=true`) and is stripped again at normalization. For the location of a secret alert, list paths and lines only:

  ```bash
  gh api --hostname <host> "repos/<owner/name>/secret-scanning/alerts/<n>/locations" \
    --jq '.[] | {type, path: .details.path, start_line: .details.start_line, end_line: .details.end_line, start_column: .details.start_column, end_column: .details.end_column, commit_sha: .details.commit_sha}'
  ```

  Never print any other field, and never read the file region that holds the secret (no Read tool, `cat`, `grep` or `git show` on it). If you need the line's structure, use `python3 <skill-dir>/scripts/secret_redact.py show <path> <start_line> <end_line> --commit <commit_sha> --start-column <c> --end-column <c>`, which never prints the secret span (the whole line is only a placeholder when columns are missing) and refuses, printing nothing, when the file changed since `commit_sha` (then note "location stale" in the report instead of the line) ([playbooks/secrets.md](playbooks/secrets.md)).

## Phase 2 — Stack recon

Read, when present (do not read `.env*` files or anything that looks like credentials):

| File | What to record |
|------|----------------|
| `package.json` (root and workspaces) | `@angular/core` and `@angular/cli` versions, `typescript`, `rxjs`, `zone.js`, `@angular/material`/`@angular/cdk`, third-party Angular libraries (`ngx-*`, `@ng-*`, `@ngrx/*`, `primeng`, …), `packageManager`, `engines.node`, `overrides`/`resolutions`/`pnpm.overrides`, `workspaces`, the `test`/`build`/`lint` scripts |
| Lockfile | Package manager: `package-lock.json` or `npm-shrinkwrap.json` (npm, note `lockfileVersion`), `yarn.lock` (Yarn; `.yarnrc.yml` means Yarn 2+), `pnpm-lock.yaml` (pnpm). The **installed** version of every alerted package and who pulls it in |
| `angular.json` | Projects, builders, test runner (Karma or Jest), whether Angular Material is configured |
| `composer.json` | `require.php`, `config.platform.php`, `ext-*` requirements, `scripts.test`, the framework (`laravel/framework`, `symfony/*`) |
| `composer.lock` | The installed version of every alerted package, and the `platform` section |

Also record:

- **Tests available**: `*.spec.ts` / `*.test.{js,ts}` count (`git ls-files '*.spec.ts' | wc -l`), `phpunit.xml`/`phpunit.xml.dist`, a `tests/` directory, and whether a `test` script exists. You do not run them.
- **PHP present**: `git ls-files '*.php' | head -1`. If there is PHP code, add the note "CodeQL does not analyze PHP; PHP code has no code-scanning coverage" even when `code_scanning` is `ok` (it covers the JS/TS part only).

Prefer reading files. You may run read-only inspection commands that already work locally (`npm ls <pkg>`, `yarn why <pkg>`, `pnpm why <pkg>`, `composer why <pkg>`, `composer show <pkg>`). Never use a bare `npx <tool>` that could trigger an install.

## Phase 3 — Map each open alert to a fix type

Use the stack playbooks for the details: [npm](playbooks/npm.md), [Angular](playbooks/angular.md), [Composer](playbooks/composer.md), [code scanning](playbooks/code-scanning.md), [secrets](playbooks/secrets.md).

| Fix type | Use it when |
|----------|-------------|
| `direct-bump` | The package is a direct dependency and the first patched version is a patch or minor jump from the installed version (for `0.x`, a patch jump only). Also when a healthy Dependabot PR already does it. |
| `transitive-override` | The package is transitive. First choice: an in-range lockfile refresh (the parent's declared range already accepts the patched version). Otherwise: `overrides` / `resolutions` / `pnpm.overrides` / `composer update <pkg> --with-dependencies`. Say which one. |
| `major-upgrade` | The patched version is a major jump (or a `0.x` minor jump) from the installed version, for the package itself or for the parent you must upgrade. Every `@angular/*` major hop is one of these. |
| `code-change` | A code-scanning alert that needs a code fix. |
| `rotate-secret` | Every open secret-scanning alert. Rotation comes first, regardless of anything else. |
| `dismiss-candidate` | There is concrete evidence for a GitHub dismissal reason ([dismissals.md](dismissals.md)) **and** no cheap, low-risk fix exists. A low-risk fix always beats a dismissal. |
| `no-fix-available` | `first_patched` is empty (no patched version published), or the fix is blocked (e.g. the patched version needs a PHP version the platform cannot run). Say what blocks it. |

Rules:

- Group alerts closed by the same change into one row (e.g. three alerts on `lodash`, or every `@angular/*` alert closed by the same major hop).
- Compare the **installed** version (from the lockfile) with `first_patched`, not the declared range.
- Dependabot PRs: match a PR to alerts by package name (title "Bump X from A to B", or `headRefName` `dependabot/<ecosystem>/<pkg>-<version>`) and check that its target version is ≥ `first_patched`. Health:
  - `healthy`: `mergeable` is `MERGEABLE` and every check's `conclusion` is `SUCCESS`, `NEUTRAL` or `SKIPPED`;
  - `failing`: any check concluded `FAILURE`, `TIMED_OUT`, `CANCELLED` or `ACTION_REQUIRED`;
  - `pending`: some check has no conclusion yet;
  - `conflicting`: `mergeable` is `CONFLICTING` (stale; the skill will redo the bump);
  - `unknown`: `mergeable` is `UNKNOWN`, or there are no checks at all (say "no CI checks").
  Commit-status entries carry `state` instead of `conclusion`: `SUCCESS` passes, `PENDING`/`EXPECTED` is pending, `FAILURE`/`ERROR` fails.
  A PR that crosses a major version is a `major-upgrade`, even when it is healthy.
- Code scanning: read the code at `path:start_line` and the rule (`rule_id`, `rule_description`). Classifications `test`/`generated` are a hint for a `used in tests` dismissal, not proof. Record the Autofix status from `autofix`.
- **Credential code-scanning alerts** (`credential_rule: true`: hard-coded credentials, clear-text secrets, rule ids about passwords, tokens or API keys; see [playbooks/code-scanning.md](playbooks/code-scanning.md)): the flagged line holds a credential. **Never read `path:start_line..end_line`** with the Read tool, `cat`, `grep`, `sed -n` or `git show`, and do not fetch the alert's `message.text`. If you need the line's structure, use only `python3 <skill-dir>/scripts/secret_redact.py show <path> <start_line> <end_line> --commit <commit_sha> [--start-column <start_column> --end-column <end_column>]` (the alert's `commit_sha`); if it refuses the location as stale, write "location stale" in **Evidence**. Fix type `code-change`, with "credential: rotate first (secrets.md)" in the row, and fix-risk from the "secret rotation" factor as well. In **Evidence** write only `path:line`.
- Secrets: record `secret_type`, `validity`, `publicly_leaked`, `push_protection_bypassed` and the location paths/lines. A secret in a test fixture is still `rotate-secret` unless it is clearly a fake, non-working value; then it may be a `dismiss-candidate` (`used_in_tests`) with that evidence.
- Ecosystems outside v1 (Maven, pip, Go, …): map them with generic guidance (direct vs transitive, semver jump) and say "generic guidance only" in the row.

## Phase 4 — Apply the risk model

For every row, assign the fix-risk level (`low` / `medium` / `high`) and list the concrete factors behind it, using [risk-model.md](risk-model.md). The level is the highest level of any factor. Never blend fix-risk with priority.

## Analysis Report (output contract)

End with exactly this structure, in English, compact, with no raw JSON dumps. Never include a secret value.

```markdown
## Analysis Report — github-security-remediation

**Repo:** <owner/name> · **Host:** <host> · **Visibility:** <PUBLIC|PRIVATE|INTERNAL> · **Default branch:** <name> · **Generated at:** <generated_at>
**Stack:** Angular <x.y.z | none> · package manager <npm (lockfileVersion N) | yarn 1 | yarn 2+ | pnpm | none> · PHP <`require.php` constraint, `config.platform.php` if set, required `ext-*` | none>
**Tests:** <e.g. `npm test` (Karma), 42 *.spec.ts; `composer test` (PHPUnit) | none found>
**Coverage:** dependabot <value> · code_scanning <value> · secret_scanning <value><; CodeQL does not analyze PHP: PHP code has no code-scanning coverage>
**Open alerts:** <N> — dependabot <a>, code_scanning <b>, secret_scanning <c> · critical <..>, high <..>, medium <..>, low <..> · P1 <..>, P2 <..>, P3 <..>
**Already closed on GitHub:** <closed_known>

### Alerts

| # | Alert(s) | Source | Severity | Priority / band | Fix type | Fix-risk + factors | Evidence |
|---|----------|--------|----------|-----------------|----------|--------------------|----------|
| 1 | secret_scanning#3 (aws_access_key_id) | secret_scanning | critical | 85 / P1 | rotate-secret | medium: 2 known consumers (CI, staging) | validity active; config/deploy.yml:12 |
| 2 | dependabot#2 lodash GHSA-35jh-r3h4-6jhm | dependabot | high | 75 / P1 | transitive-override | low: patch 4.17.20→4.17.21, in-range lockfile refresh, tests present | package-lock: lodash 4.17.20 via <parent> (^4.17.15); PR #7 healthy |
| 3 | dependabot#1 @angular/core GHSA-c75v-2vq8-873c | dependabot | critical | 70 / P1 | direct-bump | low: patch 11.0.0→11.0.5 within major 11, all `@angular/*` move together, manifests and lockfile only, tests present | package-lock: @angular/core 11.0.0; first_patched 11.0.5 |
| 4 | dependabot#3 karma GHSA-7x7c-qm48-pq9c | dependabot | medium | 25 / P3 | major-upgrade | high: major 5.1→6.3.16 of the test runner (devDependency), `karma.conf.js` may change | package.json karma ~5.1.0 (devDependencies); first_patched 6.3.16 |

### Existing Dependabot PRs

| PR | Title | Bump (jump) | Alerts it closes | Health | Notes |
|----|-------|-------------|------------------|--------|-------|
| #7 | Bump lodash from 4.17.20 to 4.17.21 | lodash 4.17.20→4.17.21 (patch) | dependabot#2 | healthy (MERGEABLE, checks SUCCESS) | — |

### Notes
- <coverage gaps and what they mean; blockers; spot-check hints; anything the skill must know>
```

Rules for the report:

- One row per fix unit. `Alert(s)` uses `<source>#<number>` plus the package/rule/secret type and the GHSA id when there is one.
- `Priority / band` is copied from the CLI output. For a grouped row, use the highest priority in the group.
- `Fix-risk + factors` starts with the level, then the factors from `risk-model.md` that set it.
- `Evidence` names what you actually checked: lockfile line, `npm ls`/`composer why` output, PR health, `path:line`. It is the first thing the skill spot-checks.
- If there are no open Dependabot PRs, write "none". If an alert source has no coverage, say so in **Coverage** and **Notes**; never report it as zero alerts.
