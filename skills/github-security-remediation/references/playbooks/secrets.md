# Playbook — Secret scanning alerts

An exposed credential is the most urgent item in any plan: it is always **block 1**. Removing it from the code does **not** fix it: anyone who read the repo (or its history, forks, clones, CI logs) may already have it. The only fix is to make the exposed value useless.

## Never display the value

These rules apply to **every** step that touches a secret: analysis, planning, editing, verifying, committing, PRs, dismissals.

- Alerts are fetched with `hide_secret=true`, and the scripts strip any `secret` field again. Never call the secret-scanning API without `hide_secret=true`.
- Refer to a secret only by its **alert link, `secret_type` (display name), `validity`, and `path:line`** (from the locations endpoint, see [../repo-analysis.md](../repo-analysis.md)). When a value must be mentioned, write `[redacted]` (or the type's public prefix only, e.g. `AKIA…[redacted]`).
- Never put a secret-bearing line in the conversation. That rules out the Read tool, `cat`, `sed -n`, `grep`, `git show`, `git diff`, `git log -p` and `git blame` on a secret-bearing file region, and the Edit tool on those lines (it needs the old text). Use `secret_redact.py` instead (below). Never open `.env*` files.
- Commits: stage by explicit path, check with `git diff --cached --stat` or `secret_redact.py diff --cached`, never `git commit -v` or `git add -p`. After committing, `git show --stat HEAD`. Commit messages, PR bodies and dismissal comments never contain any part of the value.
- If a secret value ever appears in your context by accident, do not repeat it, do not write it to any file, plan, commit, comment or report, and tell the developer that it should be treated as exposed.

### `secret_redact.py`: work on the line without seeing the value

Get `path`, `start_line`, `end_line`, `start_column`, `end_column` and `commit_sha` from the alert's locations (repo-analysis.md, Phase 1). An alert can have several locations: handle each one that is still in the working tree separately. Then:

```bash
# 1. Look at the line. Without columns, or for a multi-line secret (private key), every line of the location is
#    printed only as `<path>:<n>: [line redacted: secret-bearing]`. With the columns of a single-line location, the
#    line is shown with exactly that span replaced by `[redacted]` (e.g. `machine h login u password [redacted]`).
#    No surrounding lines are ever printed.
python3 <skill-dir>/scripts/secret_redact.py show <path> <start_line> <end_line> --commit <commit_sha> \
  [--start-column <start_column> --end-column <end_column>]

# 2. Replace exactly those lines with the configuration reference you composed. Only those bytes change.
python3 <skill-dir>/scripts/secret_redact.py replace <path> <start_line> <end_line> --commit <commit_sha> <<'EOF'
  accessKeyId: process.env.AWS_ACCESS_KEY_ID,
EOF

# 3. Verify the change by structure only: files, hunk ranges and line numbers. Changed lines are never printed.
python3 <skill-dir>/scripts/secret_redact.py diff <path>
```

- Without columns you cannot see the line's structure (the key name). Ask the developer to tell you what surrounds the value, or let them make the edit. Never guess by reading the file another way.
- To show the developer the change, show the **replacement text you wrote** (step 2's input, which never contains the secret) next to the structure from step 3, e.g. "`config/deploy.js` line 12 (`AKIA…[redacted]`) → `  accessKeyId: process.env.AWS_ACCESS_KEY_ID,`".
- **Stale locations are refused by the script, before anything is printed or written.** The line numbers come from the commit where GitHub found the secret (`commit_sha`). `show` and `replace` require `--commit <commit_sha>` and first check, silently, that lines `<start_line>..<end_line>` of the working file are byte-identical to the same lines of `<path>` at that commit. If lines were added or changed above or on the secret since then, they print only `{"error": "alert location is stale: file changed since <sha7>", …}` and exit 2, and `replace` leaves the file untouched. Then stop: re-run `analyze_repo.py` (GitHub may report a newer location), or ask the developer to locate the secret or make the edit. Never search for the line yourself.
- `alert location not found at <sha7>` means the commit is not in the local clone or the path did not exist there. Run `git fetch origin` once and retry; if it still fails, ask the developer.
- `diff --cached` checks the staged change, and `diff --commit <rev>` checks a commit. All of them call git with `--no-color --no-ext-diff --no-textconv -U0 --inter-hunk-context=0`, and refuse (JSON error, nothing printed) merge commits and any output they cannot parse.
- On any `{"error": …, "hint": …}` (stale location, unknown commit, line range out of range, no such file, merge commit, unparseable diff), stop and ask.

## Order of operations

Every secret block follows this order. Steps 1–3 happen **outside the repo** and are done by a human; you prepare them and wait.

1. **Revoke or rotate at the provider** (cloud console, SaaS dashboard, vault). Name the provider from `secret_type` (e.g. AWS access key → IAM; GitHub token → the token owner's settings; Slack webhook → the Slack app). If the type is generic, ask the developer who issued it.
2. **Issue the replacement** credential, stored in the proper place (vault, CI/CD secret store, environment config), never in the repo.
3. **Update every consumer** to the new credential: CI/CD variables, deployed services, other repos, teammates' local configs. Unknown consumers are a high fix-risk factor: plan an overlap window if the provider allows two valid credentials at once.
4. **Remove it from the code**: an application code change, so it is approved first, but the approval works on a **description**, never on a diff that shows the value:
   - describe it by file and line, with the value redacted: "In `config/deploy.js` line 12, replace the literal `accessKeyId` value (`AKIA…[redacted]`) with `process.env.AWS_ACCESS_KEY_ID`";
   - the developer either makes the edit themselves (then **Who acts** is the developer) or lets you make it with `secret_redact.py replace`, after which you show only the replacement text you wrote and the structure from `secret_redact.py diff <path>`;
   - replace the literal with a reference to configuration (environment variable, secret manager lookup), and add a `.gitignore` rule if a whole config file held it.
5. **History rewrite: optional, the developer's decision.** Once the credential is revoked, it is useless in history too, so rewriting history is usually not required. If the developer wants it anyway (policy, compliance), explain that it rewrites every later commit, requires a force-push and every clone to re-sync, and does not reach forks or existing clones. **This skill never rewrites history and never force-pushes**: the developer does it with their own tooling, if at all.

`validity: active` and `publicly_leaked: true` make steps 1–3 urgent: say so at the top of the plan, in the developer's language.

## Resolving the alert

- Resolve as `revoked` **only after the human confirms** that step 1 is done ("I revoked/rotated it"). Ask explicitly; do not infer it from the code change.
- Use [../dismissals.md](../dismissals.md) with `--source secret_scanning --reason revoked` and a comment in the developer's language that says who rotated it and when, without any part of the value. Example: `Key revoked in IAM and replaced via the CI secret store by jdoe, 2026-11-11.`
- A secret-scanning alert never closes by itself when the secret leaves the code. Resolving it is the step that closes it, and it then shows in the daily report's dismissals audit.
- `false_positive` / `used_in_tests`: only with evidence that the value cannot authenticate anywhere (a documented example key, a fake fixture), confirmed by the developer.

## In the plan

- **Goal**: "the exposed <type> no longer works, and the code reads it from configuration".
- **Who acts**: human outside the repo (steps 1–3); developer or agent for step 4 (the agent only via `secret_redact.py`, after approving the redacted description); developer (confirms rotation; decides on history).
- **Fix-risk**: from the "secret rotation" row of [../risk-model.md](../risk-model.md) (consumers to update), plus the files changed in step 4.
- **Verification**: the provider shows the old credential as revoked; the services using the new one work; the alert is resolved as `revoked`.
