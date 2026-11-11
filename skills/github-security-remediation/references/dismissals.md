# Dismissals

A dismissal closes an alert **without fixing it**. It is legitimate only with evidence, a GitHub reason, a justification comment, and the developer's confirmation of **that exact alert**. Dismissing silently, in bulk, or to make numbers look better is a failure of this skill.

Every dismissal is audited: it is made with the developer's own `gh` account (GitHub records them as `dismissed_by` / `resolved_by`), and the daily portfolio report lists who dismissed what, with which reason and comment, in its **Dismissals audit** section. Write each comment as if the security team will read it, because it will.

## When a dismissal is legitimate

Prefer a fix whenever a low-risk one exists. Do not dismiss alerts that the working branch already fixes: they close by themselves once the branch is integrated, and dismissing them would hide them from tracking.

### Dependabot (`dismissed_reason`)

| Reason | Legitimate when | Evidence to cite |
|--------|-----------------|------------------|
| `fix_started` | A fix exists outside this session and is about to land (an open PR or branch owned by someone else), and the developer wants the alert out of the queue meanwhile | PR link or branch name |
| `inaccurate` | The alert is wrong: the lockfile already resolves a patched version, the manifest was misread, or the advisory range does not match the installed version | Lockfile line with the installed version |
| `no_bandwidth` | The developer explicitly decides not to fix it now and accepts that it stays a known risk. Weak; suggest a follow-up date | The decision and the date |
| `not_used` | The vulnerable package or function is not reachable: it is not imported anywhere, or only by code that is never shipped. A `development` scope alone is not enough when build tooling processes untrusted input | `git grep` result, or the build config showing it is excluded |
| `tolerable_risk` | The risk is real but acceptable in this context (dev-only tool with no untrusted input, mitigated by the environment), and the developer accepts it | Why it is tolerable, and who accepted it |

### Code scanning (`dismissed_reason`)

| Reason | Legitimate when | Evidence to cite |
|--------|-----------------|------------------|
| `false positive` | The flagged flow cannot happen: the input is validated or encoded before the sink, or the value is constant | `path:line` of the sanitizer or the constant |
| `won't fix` | The owner accepts the issue, e.g. code scheduled for removal or behind an admin-only path, with a reason | The decision, and the removal plan if there is one |
| `used in tests` | The code only exists in tests, fixtures or test helpers and is never shipped | The path, plus the build config if relevant |
| `mitigated` | A control outside the flagged code neutralizes it (framework auto-escaping, a WAF rule, a hardened runtime setting) | Where the control lives |

See [playbooks/code-scanning.md](playbooks/code-scanning.md) for checking false positives before proposing one.

### Secret scanning (`resolution`)

| Reason | Legitimate when | Evidence to cite |
|--------|-----------------|------------------|
| `revoked` | **Only after a human confirms** that the credential was revoked or rotated at the provider ([playbooks/secrets.md](playbooks/secrets.md)) | Who confirmed, and when |
| `false_positive` | It is not a credential: a documented example key, a hash, a random string that matches the pattern | Why it cannot authenticate anywhere |
| `used_in_tests` | A fake credential in a test fixture that works nowhere, confirmed by the developer | The fixture path |
| `wont_fix` | Rare. The owner explicitly accepts a live credential staying exposed. Push back and recommend rotation first | The owner's explicit decision |

Never quote the secret value, or any part of it, in a comment.

## Writing the comment

- **≤280 characters** (`dismiss.py` refuses longer ones), in the **developer's language**.
- Say *why*, cite the *evidence*, and name *who decided*. Optionally a follow-up date.
- Keep the reason enum itself untranslated (it is an API value); translate only the comment.
- No secret values, no tokens, no internal URLs that would leak in a public repo.

Template: `<why, in plain words>. <evidence>. Decided by <name or login>, <YYYY-MM-DD>.`

- English: `Only used by the local Karma runner, never shipped; no untrusted input reaches it. Decided by jdoe, 2026-11-11.`
- Spanish: `Solo lo usa Karma en local, nunca llega a producción ni recibe entradas no confiables. Decidido por jdoe, 2026-11-11.`

## Procedure (main thread only)

The subagent never dismisses. Only the main thread runs `dismiss.py`, one alert at a time.

1. **Propose** each alert on its own, in the developer's language: the alert link, the proposed reason, the draft comment and its character count, and the evidence.
2. **Ask** for that alert: dismiss it, change the reason/comment, or skip it. A reply that names each alert ("yes to dependabot#3 and code-scanning#5") counts as confirming those alerts. "Dismiss all of them" without each alert having been shown with its reason and comment does not count: show them first.
3. **Dry-run**, then dismiss:

   ```bash
   python3 <skill-dir>/scripts/dismiss.py --repo <owner/name> --host <host> \
     --source dependabot --number 3 --reason tolerable_risk \
     --comment 'Only used by the local Karma runner, never shipped. Decided by jdoe, 2026-11-11.' --dry-run
   # same command without --dry-run once the developer said yes
   ```

   - `--source` is `dependabot`, `code_scanning` or `secret_scanning`. Secret-scanning alerts are resolved (`state: resolved`, `resolution`), the others dismissed.
   - Reasons with spaces or apostrophes must be quoted: `--reason "won't fix"`, `--reason "false positive"`.
   - Put the comment in single quotes; write an apostrophe inside it as `'\''`.
   - `--dry-run` prints the PATCH it would send and makes no API call.
4. **Check the result**: on success the CLI prints `{"number": …, "state": "dismissed" | "resolved", "reason": …}`. On `{"error": …, "hint": …}` (e.g. HTTP 403: the account lacks write or security permissions on the repo), stop and tell the developer. Do not retry with other reasons.
5. **Record** each dismissal for the wrap-up: alert, reason, comment, who confirmed.

A dismissal can be undone by reopening the alert from its GitHub page. Mention it if the developer hesitates.
