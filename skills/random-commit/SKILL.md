---
name: random-commit
description: Group all pending git changes into separate semantic (Conventional Commits) commits by intent, then push the current branch. User-invoked only — run as /random-commit [optional context for commit messages].
argument-hint: "[optional context for commit messages]"
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*), Bash(git -c commit.gpgsign=false commit:*), Bash(git push:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git config --get:*)
---

# Random Commit

Group all current changes into meaningful semantic commits on the current branch, then push.

Optional context for commit messages: `$ARGUMENTS`
(If that placeholder was not substituted by your agent, use whatever text the user wrote after the command, or treat it as empty.)

## Step 1 — Inspect the repository

Run these and read the output before deciding anything:

```bash
git rev-parse --abbrev-ref HEAD
git status
git diff --stat
git diff --cached --stat
git log --oneline -10
```

Then read the actual changes **per file** (`git diff -- <file>`, `git diff --cached -- <file>`, or the file itself when untracked). On a large change set, don't dump the whole `git diff` at once.

Stop and tell the user when:
- the branch is `HEAD` (detached): there is no branch to push;
- `git status` says a merge, rebase, cherry-pick or revert is in progress ("You are currently rebasing", "All conflicts fixed but you are still merging", unmerged paths…);
- there is nothing to commit.

## Rules

- Group files by intent: feature, fix, refactor, tests, docs, chore, release, or config.
- Create multiple commits when changes are independent. Never mix unrelated changes in one commit.
- A file whose changes belong to two groups goes whole into the group of its main change (`git add -p` is interactive and not available). Mention it in the plan.
- If context was given, use it to shape the messages, but don't force it where it doesn't describe the change.
- Messages: clear, semantic, concise, matching the repo's recent style (from `git log`). Also follow any commit conventions in project or user instructions (`AGENTS.md`, `CLAUDE.md`, etc.) — e.g. forbidden trailers.
- **Secrets.** Before committing, check file names (`.env*`, `*.pem`, `*.key`, `id_rsa*`, credentials, tokens) **and** the added lines of each diff for key-like values (`AKIA…`, `ghp_…`, `github_pat_…`, `sk-…`, `xox[bp]-…`, `-----BEGIN … PRIVATE KEY-----`, `password=`/`secret=` with a literal value). If anything matches, **stop and ask**. Never print the value back; name the file and line.
- Include new, modified, and deleted files that belong to each group.
- **Signing.** Sign when available: commit with plain `git commit`, which follows the user's `commit.gpgsign`. Never pass `commit.gpgsign=false` up front. Only if a commit fails **because signing failed** (no agent, pinentry needs a TTY, missing key) retry that commit with `git -c commit.gpgsign=false commit`, and list the unsigned commits in the summary with the signing error.
- Do not revert existing changes. Do not use `--no-verify`. Do not amend. Do not force push.
- If a pre-commit hook fails, stop, report the output, and ask — do not bypass it. If a hook modified files (formatter, lint-staged), show what changed and ask before staging them.

## Flow

1. Show the proposed commit plan: each commit message with its files.
2. If the grouping is clear, continue. If there is real ambiguity, ask before committing.
3. For each group:
   - `git add <files of this group only>` (use `git add -- <path>` for deletions and paths starting with `-`).
   - `git commit -m "<subject>"` (add `-m "<body>"` when the why isn't obvious).
4. Push: `git push`. If the branch has no upstream, use `git push -u origin <branch>`. If the push is rejected (remote has new commits, protected branch), stop and report: don't pull, rebase or force on your own.
5. Summarize the commits created (hash + subject, marking any unsigned ones) and the branch pushed.
