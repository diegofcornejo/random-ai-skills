# Guided Execution

Execution runs in the **main conversation**, block by block, only for the blocks the developer approved. Everything the developer reads (progress, questions, diffs explained, the wrap-up) is in the developer's language.

## 0. Before the first block

1. **Restate** the approved blocks and their order in one short list.
2. **Ask once** whether you may run the project's install and verification commands (section 4). If not, you will list the commands for the developer to run after each block and wait for the result.
3. **Baseline**: if allowed, run the verification commands on the untouched tree and record pass/fail per command. A later failure only counts against a block if the baseline passed.
4. **Working branch**: propose `security/remediation-<YYYY-MM-DD>` and confirm the name. If the current branch is not the default branch, ask whether to start from it or from the default branch (`git fetch origin <default>` then `git switch -c <branch> origin/<default>`). Otherwise `git switch -c <branch>`.
5. **Setup commit**: if the report-file decision changed `.gitignore` or created `.github-security-remediation.json` (and, when `commit_reports` is `true`, `SECURITY-REMEDIATION.md`), commit exactly those files first, e.g. `chore(security): add remediation plan settings`, and tell the developer.

## 1. The block loop

For each approved block, in plan order:

1. `git status --porcelain` must be clean. If not, stop and ask (the previous block may be uncommitted).
2. Do the block's steps, following the rules in section 2 and the stack playbook.
3. Verify (section 4). On failure, stop (section 5).
4. Commit the block: **one commit per block**.
   - Stage explicit paths (`git add package.json package-lock.json`), not `git add -A`.
   - Follow the repo's commit convention (`git log --oneline -10`); default to Conventional Commits, e.g. `fix(deps): bump lodash to 4.17.21 (block 2)`.
   - In the body, reference the alerts by URL (`https://<host>/<owner>/<repo>/security/dependabot/2`) or as "Dependabot alert 2". **Never** `Closes #2` / `Fixes #2`: GitHub would close the issue or PR numbered 2.
   - If `SECURITY-REMEDIATION.md` is versioned, mark the block as done in it and include it in the same commit.
5. Tell the developer, in one or two lines: what changed, verification result, commit hash. Continue with the next approved block.

## 2. Rules per kind of change

### Mechanical changes: no per-file approval once the block is approved

Lockfile and manifest bumps, `overrides` / `resolutions` / `pnpm.overrides` entries, `composer update <pkg> --with-dependencies`, and bringing in a green Dependabot PR's change. Use the playbooks: [npm](playbooks/npm.md), [Composer](playbooks/composer.md). Show the resulting `git diff --stat` before committing.

If a "mechanical" step turns out to need application code changes (a type error after a bump, a removed API), stop treating it as mechanical: explain, and switch to the application-code rule.

### Existing Dependabot PRs: never `gh pr merge`

Never merge them with `gh pr merge` (or any other merge call): they target the default branch, and integration is the developer's choice. Bring the PR's change into the working branch as that block's commit instead.

1. Check it again: `gh pr view <n> --json state,mergeable,statusCheckRollup,headRefName`.
2. **Healthy and fresh**: fetch it and apply it without committing, so that one block stays one commit even with several PRs:

   ```bash
   git fetch origin <headRefName>
   git log --oneline "$(git merge-base HEAD FETCH_HEAD)"..FETCH_HEAD   # expect Dependabot's commit(s) only
   git cherry-pick --no-commit <sha>                                    # each listed commit, oldest first
   ```

3. **Stale, conflicting, or failing**: do not fight the conflict. If a cherry-pick conflicts, run `git cherry-pick --abort`; if git says no cherry-pick is in progress, restore only the files it touched with `git restore --source=HEAD --staged --worktree -- <paths>`. Then redo the same bump yourself on the current lockfile (the PR title gives the package and target version), using the playbook.
4. Commit the block, mentioning "supersedes Dependabot PR #<n>" in the body. Once the developer integrates the branch into the default branch, GitHub closes the Dependabot PR as superseded.

### Application code changes: always ask first

Code-scanning fixes, API adaptations after upgrades, Angular migration edits that `ng update` did not do automatically.

1. Show the proposed change as a diff, with one or two sentences on why it fixes the alert and what it could affect. **Exception: a change on a secret-bearing line** (a secret-scanning location, or the line of a code-scanning credential alert, `credential_rule: true`) is never shown as a plain diff; describe it by file and line with the value redacted, show only the replacement text you wrote, and check it with `secret_redact.py diff` (structure only). `show`/`replace` need the location's `--commit <commit_sha>` and refuse a stale location; then stop and ask ([playbooks/secrets.md](playbooks/secrets.md)).
2. Ask: apply it, change it, or skip it. The developer may also tell you what to do instead.
3. Apply only what was approved. A new or different change is a new question.

Playbooks: [code scanning](playbooks/code-scanning.md), [Angular](playbooks/angular.md).

### Secrets: never "fixed" in code alone

Follow [playbooks/secrets.md](playbooks/secrets.md): rotation steps for a human (revoke/rotate at the provider → issue the new one → update consumers → remove from code → optional history rewrite, decided by the developer). Resolve the alert as `revoked` only after the human confirms the rotation. Never print, copy or quote the value: in this block, never run `git diff`, `git show`, `git log -p`, `cat` or the Read/Edit tools on secret-bearing lines, including when staging and committing. Use `secret_redact.py show|replace|diff`, `git diff --cached --stat` and `git show --stat HEAD` instead.

### Dismissals: one confirmation per alert

Follow [dismissals.md](dismissals.md): propose the reason (GitHub's enum) and a comment of ≤280 characters in the developer's language, get a yes for that exact alert, then run `dismiss.py`. A dismissal block has no commit (nothing changes in the repo), unless the plan file is versioned and you mark the block done.

## 3. Angular major hops

Each hop (11→12, 12→13, …) is its own block, verified and committed separately. Ask before running `ng update` (it downloads and installs packages). Details in [playbooks/angular.md](playbooks/angular.md).

## 4. Verification commands per stack

Prefer the project's own scripts (`package.json` `scripts`, `composer.json` `scripts`) over the generic commands. Run installs only with the permission from step 0.

| Stack | Install after lockfile changes | Verify |
|-------|-------------------------------|--------|
| npm | `npm ci` | `npm test`, `npm run build`, `npm run lint` (when defined); TypeScript without Angular: `npx --no-install tsc --noEmit` |
| Yarn 1 | `yarn install --frozen-lockfile` | `yarn test`, `yarn build`, `yarn lint` |
| Yarn 2+ | `yarn install --immutable` | `yarn test`, `yarn build`, `yarn lint` |
| pnpm | `pnpm install --frozen-lockfile` | `pnpm test`, `pnpm build`, `pnpm lint` |
| Angular | as its package manager | `npx --no-install ng build`; `npx --no-install ng test --watch=false` (Karma needs a browser: add `--browsers=ChromeHeadless` when the Karma config supports it); `npx --no-install ng lint` when a lint builder is configured |
| Composer | `composer install` | `composer validate --no-check-publish`; `composer test` when `scripts.test` exists, otherwise `vendor/bin/phpunit`; `php -l` on every changed PHP file: `for f in $(git diff --name-only --diff-filter=ACM HEAD -- '*.php'); do php -l "$f"; done` |

Never install global tools (Angular CLI, Chrome, PHP extensions) without asking. A command that cannot run (no browser, no database) is reported as "not run" with the reason, and the block's fix-risk note says so.

## 5. When verification fails

1. **Stop.** Do not start the next block.
2. Report exactly what broke (command, first relevant error lines), and whether the baseline passed.
3. Propose reverting the block:
   - not committed yet: `git restore --staged --worktree -- <the block's files>`;
   - already committed: `git revert <sha>` (adds a reverting commit; history stays intact).
4. Or propose a fix. A fix to application code follows the "always ask first" rule.

Never use `git reset --hard`, `git clean`, `git checkout -- .` over the whole tree, or force-push.

## 6. Integration options

When the approved blocks are done (or the developer wants to stop), offer this menu, in the developer's language, and do nothing until they choose:

1. **One PR per block**: `git fetch origin <default>`, then for each block `git switch -c security/block-<n> origin/<default>`, `git cherry-pick <block sha>`, `git push -u origin security/block-<n>`, `gh pr create --base <default> --head security/block-<n> --title "<title>" --body-file "$body"`. Blocks that depend on another block go after it (say so, or stack them).
2. **One PR** for the whole branch: `git push -u origin <branch>`, then `gh pr create --base <default> --head <branch> --title "<title>" --body-file "$body"`.
3. **Push the branch only**: `git push -u origin <branch>`; the developer opens the PR.
4. **Keep it local**: nothing leaves the machine.

Write each PR body to a temporary file outside the repo (`body=$(mktemp)`), so the tree stays clean and the body is never committed. PR titles and bodies are in the developer's language. A PR body lists only what that PR fixes (alert links, GHSA/CVE ids, verification run). It never lists the alerts that remain open, and never includes secret values or the locations of unrotated secrets, especially on a public repo. Never `gh pr merge`, never force-push.

## 7. Wrap-up

1. Re-run the analysis (same command as [repo-analysis.md](repo-analysis.md) Phase 1).
2. Report, in the developer's language:

   | Group | What to list |
   |-------|--------------|
   | **Expected to close** | Alerts fixed on the branch, still open on GitHub. |
   | **Already closed** | Alerts now dismissed or resolved on GitHub (including the ones dismissed in this session), or already fixed on the default branch. |
   | **Dismissals made** | Alert, reason, comment, who confirmed. |
   | **Remaining, and why** | No patch available, blocked by an upgrade not approved, waiting on a human (rotation, licensing), out of scope. |

3. Say explicitly: **alerts fixed on the branch only close after the branch is integrated into the default branch.** Dependabot re-evaluates the default branch's manifests; code scanning closes an alert after the next analysis of the default branch; a secret-scanning alert closes only when it is resolved, never just because the secret left the code.
4. Suggest the next step: integrate (section 6), then re-run this skill to confirm, and for the security team the daily portfolio report.
