# random-ai-skills

A collection of [Agent Skills](https://agentskills.io/) — plus the **subagents** and commands that pair with them — by [@diegofcornejo](https://github.com/diegofcornejo) for Claude Code, OpenCode, Cursor, Codex, Copilot, and any agent that supports the skills format.

## Skills vs. subagents (how they work together)

| | Skill | Subagent |
|---|---|---|
| What it is | Instructions loaded **into the current conversation** when relevant | A separate agent with **its own context**, tools, and model |
| Sees the conversation | Yes — interactive, can ask and wait for approval | No — gets a prompt, returns one final report |
| Portable | Yes (agentskills.io format, any agent) | Agent-specific (Claude Code, OpenCode) |
| Best for | Workflows that need the user: plans, approvals, edits | Heavy, read-only work whose raw output would flood the main context |

In this repo the **skill is the orchestrator and the single source of truth**. A companion subagent is a thin worker that reads the skill's reference files and returns a structured report. If no subagent is installed, the skill does the same work inline — so the skill always works on its own.

```
user ──▶ skill (main conversation)
           ├─ Step 1: preconditions
           ├─ Step 2: detection ──▶ subagent (own context, read-only)
           │                          └─ reads skills/<name>/references/*.md
           │          ◀── Detection Report ─┘     (or inline if no subagent)
           ├─ Step 3: plan ──▶ user approves
           └─ Step 4: execute in batches
```

## Installation

Pick **one** channel per agent — installing the same skill through two channels gives you duplicates.

### Claude Code — plugin (recommended: skill + subagent together)

```text
/plugin marketplace add diegofcornejo/random-ai-skills
/plugin install dead-code-hunter@random-ai-skills
/plugin install deepsec-findings-analyzer@random-ai-skills
/plugin install github-security-remediation@random-ai-skills
/plugin install random-git@random-ai-skills
```

Or in one step (Claude Code ≥ 2.1.275): `/plugin install dead-code-hunter --marketplace diegofcornejo/random-ai-skills`.

Plugin components are namespaced: the subagent appears as `dead-code-hunter:dead-code-hunter`, the skills as `/random-git:random-commit`, etc.

### Any agent — `npx skills` (skills only)

```bash
# whole collection
npx skills add https://github.com/diegofcornejo/random-ai-skills

# a single skill
npx skills add https://github.com/diegofcornejo/random-ai-skills --skill dead-code-hunter

# globally, for every detected agent
npx skills add https://github.com/diegofcornejo/random-ai-skills -g -a '*' -y
```

### Subagents and commands outside the plugin (OpenCode, or Claude Code without plugins)

`npx skills` only installs skills. Install the companion files with:

```bash
git clone https://github.com/diegofcornejo/random-ai-skills ~/random-ai-skills
~/random-ai-skills/scripts/install-agents.sh            # Claude Code + OpenCode
~/random-ai-skills/scripts/install-agents.sh --opencode # only OpenCode
```

It symlinks (so `git pull` updates them) and never overwrites an existing file unless you pass `--force`, which keeps a `.bak.<timestamp>` copy. `--dry-run` shows what would change.

| Source in this repo | Installed to |
|---|---|
| `agents/*.md` | `~/.claude/agents/` |
| `opencode/agents/*.md` | `~/.config/opencode/agents/` |
| `opencode/commands/*.md` | `~/.config/opencode/commands/` |

`opencode/opencode.example.jsonc` and `opencode/tui.json` are reference configs; copy them by hand. Secrets are read from the environment (`{env:CONTEXT7_API_KEY}`), never committed.

## Available skills

### [dead-code-hunter](skills/dead-code-hunter) · subagent: [`dead-code-hunter`](agents/dead-code-hunter.md)

Detect and safely remove dead code in JS/TS projects (Node, React, monorepos): orphan files, unused exports and types, unused imports and locals, unreachable code, unused dependencies, and code that only tests use. It combines independent signals (knip in default and production mode, the project's own `tsc` unused-code diagnostics, `git grep`, LSP) through a bundled merge script, proposes a risk-ordered plan, and executes it in reversible, one-commit-per-batch steps only after approval. If knip isn't installed it can run it ephemerally (`npx -y knip@6`) with your permission, without touching `package.json`.

- **Skill**: orchestrates preconditions → detection → plan → approval → execution.
- **Subagent** (optional): read-only detection worker with no Edit/Write tools. It keeps analyzer output out of your main context and returns a compact Detection Report. You can also call it directly when you only want a report.

### [deepsec-findings-analyzer](skills/deepsec-findings-analyzer) · subagent: [`deepsec-finding-verifier`](agents/deepsec-finding-verifier.md)

Triage security findings from a [deepsec](https://github.com/vercel-labs/deepsec) scan: group by root cause, prioritize by impact and effort, keep triage state across sessions, and generate ticket-ready drafts.

- **Skill**: locates and validates the export, merges triage data, tracks state, and writes the report at the level you choose.
- **Subagent** (optional): read-only verifier for deep analysis. One per group of findings, run in parallel: it reads the source, rules each finding confirmed / mitigated / stale / uncertain, and drafts fixes, keeping the code out of your main context.

### [github-security-remediation](skills/github-security-remediation) · subagent: [`security-alerts-analyzer`](agents/security-alerts-analyzer.md)

Turn a repo's GitHub security alerts (Dependabot, code scanning, secret scanning) into a prioritized remediation plan and carry it out with approvals, or build a daily consolidated report across orgs and user accounts for a security team. Read-only on GitHub except dismissals you confirm; it never merges, pushes or rotates secrets on its own. [What you get, with examples →](skills/github-security-remediation/README.md)

### [random-commit](skills/random-commit) · [random-merge-to-main](skills/random-merge-to-main)

User-invoked git workflows (`disable-model-invocation: true`, so the agent never runs them on its own):

- `/random-commit [context]`: groups pending changes into semantic commits by intent, then pushes.
- `/random-merge-to-main`: fast-forward merges the current branch into `main`, pushes, and deletes the branch locally and on the remote.

In OpenCode, `opencode/commands/` provides `/random-commit` and `/random-merge-to-main` as thin wrappers that load these skills.

## Versioning and updates

**You don't need to bump versions.** Every channel detects changes from git content:

| Channel | How it detects an update | Pin a version |
|---|---|---|
| `npx skills check` / `update` | Compares the **git tree SHA of the skill folder** (`skillFolderHash` in `~/.agents/.skill-lock.json` or `skills-lock.json`) with the remote. Any change inside `skills/<name>/` is an update. Changes elsewhere (README, other skills) are not. | `npx skills add diegofcornejo/random-ai-skills@v1.2.0 --skill <name>` (tag or full commit) |
| Claude Code plugin | With no `version` in the manifest, the version **is the commit SHA** (12 chars). Every pushed commit is a new version for every plugin in this repo. Third-party marketplaces don't auto-update by default: run `/plugin marketplace update random-ai-skills`, or turn on auto-update in `/plugin` → Marketplaces. | Setting `"version"` pins users to it until you change the string. That's why this repo leaves it out on purpose. |
| `install-agents.sh` symlinks | `git pull` in your clone | `git checkout <tag>` |

Git tags (`v1.0.0`, …) are optional. They're useful for giving people a stable pin, not for making updates work.

## Repository layout

```
.claude-plugin/marketplace.json   # Claude Code marketplace: one plugin per feature
skills/{name}/                    # canonical skills (npx skills + plugin)
  SKILL.md
  references/                     # loaded on demand — also read by subagents
  scripts/  examples/
agents/{name}.md                  # Claude Code subagents (thin workers)
opencode/agents/{name}.md         # OpenCode subagents (V2 frontmatter)
opencode/commands/{name}.md       # OpenCode slash commands (wrappers over skills)
scripts/install-agents.sh         # installs agents/commands outside the plugin
scripts/validate.sh               # repo consistency checks
```

## Contributing

See [AGENTS.md](AGENTS.md) for authoring conventions (including the skill + subagent pattern) and [CLAUDE.md](CLAUDE.md) for Claude Code notes. Run `scripts/validate.sh` before pushing.

## License

MIT — see individual skills for their own licenses where applicable.
