---
name: random-merge-to-main
description: Merge the current feature branch into main (fast-forward when possible), push main, and delete the feature branch locally and on the remote. User-invoked only — run as /random-merge-to-main.
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git branch:*), Bash(git switch:*), Bash(git fetch:*), Bash(git pull:*), Bash(git merge:*), Bash(git push:*), Bash(git ls-remote:*), Bash(git symbolic-ref:*), Bash(gh pr list:*)
---

# Random Merge to Main

Merge the current branch into `main`, push, and delete the branch.

## Step 1 — Inspect the repository

```bash
git rev-parse --abbrev-ref HEAD
git status --short
git fetch origin --prune
git symbolic-ref --short refs/remotes/origin/HEAD
git rev-parse --verify --quiet origin/main
git log --oneline origin/main..HEAD
git rev-list --count origin/main..HEAD
git diff --stat origin/main...HEAD
git rev-list --count HEAD..origin/<branch>
```

Compare against `origin/main` after the fetch: a stale local `main` gives wrong counts. The last command fails when the branch was never pushed; that's fine.

## Rules

- If the current branch **is** `main`, or HEAD is detached, stop and tell the user there is nothing to merge.
- **Default branch.** If `origin/HEAD` points to something other than `origin/main` (e.g. `master`, `develop`), or `origin/main` doesn't exist, stop and ask which branch to merge into. `origin/HEAD` is often unset in repos that were not cloned; then rely on `origin/main` existing.
- The working tree must be clean. If `git status --short` is not empty, **stop and ask**.
- If the branch is more than **10 commits** ahead of `main`, **stop and ask**.
- **Remote work on the branch.** If `origin/<branch>` has commits that are not in the local branch (`HEAD..origin/<branch>` > 0), stop and ask: merging and then deleting the remote branch would lose them.
- Do not use `--no-verify`. Do not force push. Never delete `main`. Never `git reset --hard`.

## Flow

1. Summarize the branch: name, commits ahead of `main`, the commit list, and the diff stat. If `gh` is available and authenticated, also mention an open PR for the branch (`gh pr list --head <branch> --state open`): pushing the commits to `main` marks it merged.
2. If every rule passes, continue. Otherwise stop and ask.
3. `git switch main` and `git pull --ff-only`.
4. `git merge --ff-only <branch>`.
   - If that fails because `main` moved, **stop and ask** before creating a merge commit (`git merge --no-edit <branch>`): some repos want linear history. Don't rebase on your own.
   - If a merge has conflicts, stop, report the conflicted files, and ask — do not resolve them silently.
5. `git push` (pushes `main`). If it is rejected (protected branch, required PR or checks, new remote commits), stop: report the error, keep the feature branch, and tell the user local `main` is ahead of `origin/main` by the merged commits. Suggest opening a PR instead. Don't reset anything.
6. After a successful merge and push, delete the branch:
   - Local: `git branch -d <branch>` (never `-D`).
   - Remote, only if it exists (`git ls-remote --heads origin <branch>`): `git push origin --delete <branch>`.
7. Summarize: commits brought in, fast-forward vs merge commit, and which deletions were performed (local and/or remote).
