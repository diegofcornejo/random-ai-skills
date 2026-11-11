---
name: random-merge-to-main
description: Merge the current feature branch into main (fast-forward when possible), push main, and delete the feature branch locally and on the remote. User-invoked only — run as /random-merge-to-main.
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git branch:*), Bash(git checkout:*), Bash(git switch:*), Bash(git pull:*), Bash(git merge:*), Bash(git push:*), Bash(git ls-remote:*)
---

# Random Merge to Main

Merge the current branch into `main`, push, and delete the branch.

## Step 1 — Inspect the repository

```bash
git rev-parse --abbrev-ref HEAD
git status --short
git log --oneline -10
git log --oneline main..HEAD
git rev-list --count main..HEAD
git diff --stat main...HEAD
```

## Rules

- If the current branch **is** `main`, stop and tell the user there is nothing to merge.
- If `main` does not exist locally, stop and ask (the repo may use another default branch).
- The working tree must be clean. If `git status --short` is not empty, **stop and ask**.
- If the branch is more than **10 commits** ahead of `main`, **stop and ask**.
- Do not use `--no-verify`. Do not force push. Never delete `main`.

## Flow

1. Summarize the branch: name, commits ahead of `main`, the commit list, and the diff stat.
2. If clean and ≤10 commits ahead, continue. Otherwise stop and ask.
3. `git switch main` and `git pull --ff-only`.
4. `git merge --ff-only <branch>`. If that fails, fall back to `git merge --no-edit <branch>` and tell the user a merge commit was created. If the merge has conflicts, stop, report the conflicted files, and ask — do not resolve them silently.
5. `git push` (pushes `main`).
6. After a successful merge and push, delete the branch:
   - Local: `git branch -d <branch>` (never `-D`).
   - Remote, only if it exists (`git ls-remote --heads origin <branch>`): `git push origin --delete <branch>`.
7. Summarize: commits brought in, fast-forward vs merge commit, and which deletions were performed (local and/or remote).
