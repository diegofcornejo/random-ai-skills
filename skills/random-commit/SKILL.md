---
name: random-commit
description: Group all pending git changes into separate semantic (Conventional Commits) commits by intent, then push the current branch. User-invoked only — run as /random-commit [optional context for commit messages].
argument-hint: "[optional context for commit messages]"
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git -c commit.gpgsign=false commit:*), Bash(git push:*), Bash(git branch:*), Bash(git rev-parse:*)
---

# Random Commit

Group all current changes into meaningful semantic commits on the current branch, then push.

Optional context for commit messages: `$ARGUMENTS`
(If that placeholder was not substituted by your agent, use whatever text the user wrote after the command, or treat it as empty.)

## Step 1 — Inspect the repository

Run these and read the output before deciding anything:

```bash
git rev-parse --abbrev-ref HEAD
git status --short
git diff --stat
git diff
git diff --cached
git log --oneline -10
```

Include untracked files from `git status` in your grouping (read them if needed).

## Rules

- Group files by intent: feature, fix, refactor, tests, docs, chore, release, or config.
- Create multiple commits when changes are independent. Never mix unrelated changes in one commit.
- If context was given, use it to shape the messages, but don't force it where it doesn't describe the change.
- Messages: clear, semantic, concise, matching the repo's recent style (from `git log`). Also follow any commit conventions in project or user instructions (`AGENTS.md`, `CLAUDE.md`, etc.) — e.g. forbidden trailers.
- Before committing, check for sensitive files (`.env*`, tokens, credentials, keys, secrets). If any appear, **stop and ask**.
- Include new, modified, and deleted files that belong to each group.
- Commit with `git -c commit.gpgsign=false commit` (no signing).
- Do not revert existing changes. Do not use `--no-verify`. Do not amend. Do not force push.
- If a pre-commit hook fails, stop, report the output, and ask — do not bypass it.

## Flow

1. Show the proposed commit plan: each commit message with its files.
2. If the grouping is clear, continue. If there is real ambiguity, ask before committing.
3. For each group:
   - `git add <files of this group only>`
   - `git -c commit.gpgsign=false commit -m "<message>"` (add `-m "<body>"` when the why isn't obvious).
4. Push: `git push`. If the branch has no upstream, use `git push -u origin <branch>`.
5. Summarize the commits created (hash + subject) and the branch pushed.
6. If you created any temporary branch during the process, delete it after pushing.
