# Playbook — Code scanning alerts

For alerts with `source: code_scanning` (CodeQL or another SARIF tool) in JavaScript/TypeScript code. Every fix here is an **application code change**: show it and ask before applying (execution.md, "always ask first").

## 1. Understand the alert

From the analysis output: `rule_id` (e.g. `js/xss`), `rule_description`, `tool`, `severity` (from `security_severity_level`), `path`, `start_line`, `end_line`, `start_column`, `end_column`, `commit_sha`, `classifications`, `credential_rule`.

### Credential alerts: never read the line

Some rules flag the exact line that **holds a credential**: hard-coded credentials or secrets (`js/hardcoded-credentials`, CWE-798), hard-coded passwords or keys (CWE-259, CWE-321), clear-text storage or logging of sensitive data (`*/clear-text-*`, CWE-312/315/532), and anything whose rule id mentions a password, token, API key, secret or credential. `credential_rule: true` in the analysis output marks them (the scripts match broadly, so a false match only costs a redacted view). Treat these lines exactly like secret-scanning locations ([secrets.md](secrets.md), "Never display the value"):

- Never open `path:start_line..end_line` with the Read tool, `cat`, `sed -n`, `grep`, `git show`, `git diff`, `git log -p` or `git blame`, and never use the Edit tool on those lines.
- View them only with `python3 <skill-dir>/scripts/secret_redact.py show <path> <start_line> <end_line> --commit <commit_sha> [--start-column <start_column> --end-column <end_column>]`, where `commit_sha` is the alert's `most_recent_instance.commit_sha`. If it refuses the location as stale, stop and ask the developer; never search for the line another way.
- Edit them only with `secret_redact.py replace … --commit <commit_sha>`, and check the change only with `secret_redact.py diff` (structure only).
- Do not fetch the alert's `message.text` (it can quote the value) and do not use Copilot Autofix for these alerts: its suggestion can contain the value.
- A real credential in the code is exposed: removing it does not invalidate it. The block includes the rotation steps of [secrets.md](secrets.md) for a human, and rates fix-risk with the "secret rotation" row of [../risk-model.md](../risk-model.md).

1. **Read the rule help.** Get the rule's full help text (description, recommendation, examples):

   ```bash
   gh api --hostname <host> "repos/<owner/name>/code-scanning/alerts/<n>" \
     --jq '{rule: .rule.id, name: .rule.name, help: .rule.help, tags: .rule.tags, message: .most_recent_instance.message.text}'
   ```

   For a credential alert (above), drop `message` from the `--jq` filter.

   For CodeQL rules the public query help is also at `https://codeql.github.com/codeql-query-help/javascript/<rule-id-with-dashes>/` (e.g. `js-xss`).
2. **Read the code** at `path:start_line` and trace the flow the message describes (for a credential alert, only through `secret_redact.py show`, above): where the data comes from (source), where it ends up (sink), and what is in between.
3. **Decide** what it is: a real issue to fix, a false positive, test-only code, or already mitigated elsewhere.

## 2. Fix: minimal change plus a test

- Make the **smallest change that removes the vulnerable flow**, following the rule's recommendation: encode/escape at the sink, validate at the boundary, use the framework's safe API (e.g. Angular's built-in sanitization instead of `bypassSecurityTrust*`, parameterized queries instead of string concatenation, `path.resolve` plus a prefix check for path traversal).
- Do not refactor around it, rename, or "clean up" unrelated code in the same block.
- Add or extend **a test that pins the fix**: the malicious input from the rule's example must now be encoded, rejected or neutralized. If the repo has no test setup for that area, say so as a fix-risk factor and propose the test anyway.
- Show the developer the diff (code + test), why it fixes the alert, and what behaviour could change. Apply only after approval.
- The alert closes after the next code-scanning analysis of the default branch, once the branch is integrated.

## 3. Copilot Autofix: only when the API offers it

Autofix is available only on some plans and hosts. `analyze_repo.py` reports its status per alert in `autofix` (`unavailable` when the endpoint did not answer). Never use it for a credential alert (`credential_rule: true`).

- Only `success` gives a usable candidate: read it with `gh api --hostname <host> "repos/<owner/name>/code-scanning/alerts/<n>/autofix"` and use its description as a candidate fix. `pending`: re-check later. `error` or `outdated`: no usable suggestion.
- `unavailable` means either "no suggestion generated yet" or "Autofix is not available here"; the CLI cannot tell them apart. You may offer, once, to request a suggestion (`POST …/alerts/<n>/autofix`). It is a write on GitHub, so ask the developer first. If the POST fails, Autofix is not available: drop it for this repo.
- Do not tell the user to buy Autofix, and do not mention it in the plan unless a `success` suggestion exists.
- Whatever Autofix proposes is treated exactly like your own proposal: **show it and ask**. Apply it as a normal local edit on the working branch, inside that block's commit. **Never** let anything commit it automatically, and never push it.

## 4. False positives and other non-fixes

Before proposing a dismissal, check:

- **False positive**: show the exact line that makes the flow impossible (the sanitizer, the constant, the type that cannot carry user input). "Looks safe" is not evidence.
- **Used in tests**: the `classifications` `test`/`generated` are a hint; confirm that the file is never shipped (test directories, `*.spec.ts`, build config excludes).
- **Mitigated**: name the control (framework auto-escaping, a CSP, a gateway rule) and where it lives.
- **Won't fix**: only with an explicit owner decision.

Then follow [../dismissals.md](../dismissals.md): reason from the code-scanning enum (`false positive`, `won't fix`, `used in tests`, `mitigated`), a ≤280-character comment in the developer's language, and per-alert confirmation.

## 5. Grouping in the plan

One block per rule (all `js/xss` alerts together), or per small group of closely related files. Fix-risk follows the "code-scanning fix" and "files that must change" rows of [../risk-model.md](../risk-model.md).
