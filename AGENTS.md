# AGENTS.md

Guidance for AI coding agents (Claude Code, OpenCode, Cursor, Copilot, Codex, Gemini CLI, etc.) working in this repository.

## Repository Overview

A personal collection of [Agent Skills](https://agentskills.io/) plus their companion **subagents** and **commands**.

- Skills live under `skills/{skill-name}/` and are distributed via [`npx skills`](https://www.npmjs.com/package/skills) and as Claude Code plugins (`.claude-plugin/marketplace.json`).
- Subagents live under `agents/` (Claude Code) and `opencode/agents/` (OpenCode). Commands live under `opencode/commands/`.

## Directory Structure

```
.claude-plugin/
  marketplace.json        # one plugin entry per feature (source "./")
skills/
  {skill-name}/           # kebab-case
    SKILL.md              # REQUIRED — frontmatter + instructions
    README.md             # optional — human-facing docs
    references/           # optional — docs loaded on demand (also read by subagents)
    scripts/              # optional — helper scripts (.sh, .py, .ts)
    examples/             # optional — sample inputs/outputs
agents/
  {agent-name}.md         # Claude Code subagent
opencode/
  agents/{agent-name}.md  # OpenCode subagent (V2 frontmatter)
  commands/{name}.md      # OpenCode slash command (thin wrapper over a skill)
scripts/
  install-agents.sh       # symlinks agents/commands into ~/.claude and ~/.config/opencode
  validate.sh             # consistency checks — run before pushing
```

## Naming Conventions

- **Skill directory**: `kebab-case` (e.g. `deepsec-findings-analyzer`)
- **`SKILL.md`**: exact filename, uppercase
- **Scripts**: `kebab-case.{sh,py,ts}`
- Directory name MUST match the `name:` field in `SKILL.md`. `npx skills add --skill <name>` matches against it.
- A companion subagent uses the **same name** as its skill (`agents/dead-code-hunter.md` ↔ `skills/dead-code-hunter/`).

## SKILL.md Format

```markdown
---
name: {skill-name}
description: {One sentence. Include trigger phrases the agent will pattern-match on.}
---

# {Skill Title}

Brief description.

## Workflow

1. Step
2. Step
```

### Frontmatter rules

- `name`: must match the directory name, kebab-case.
- `description`: must include concrete trigger phrases (file names, commands, keywords). It is the only part loaded at startup.
- Optional, agent-specific fields are fine; agents that don't know a field ignore it:
  - `disable-model-invocation: true`: user-invoked only (Claude Code, OpenCode). Use it for anything with side effects such as push, merge, or deploy.
  - `allowed-tools`, `argument-hint`: Claude Code.
- Keep the body **portable**. Don't rely on Claude-only syntax such as `` !`cmd` `` context injection; write "run these commands" steps instead.

### Script paths

Scripts are invoked from the user's project, not from the skill folder. Always write script references so the agent resolves them against the skill directory (see the "Script paths" section in `deepsec-findings-analyzer/SKILL.md`). A bare `python3 scripts/x.py` fails once the skill is installed.

## The Skill + Subagent Pattern

Use it when part of a skill's workflow is **heavy and read-only** (scanning, analyzers, large greps) and the rest needs the **user** (plans, approvals, edits).

| Role | Lives in | Owns |
|------|----------|------|
| **Skill** = orchestrator + single source of truth | `skills/{name}/SKILL.md` + `references/` | Preconditions, user interaction, plan, approval, execution, golden rules |
| **Subagent** = thin worker | `agents/{name}.md`, `opencode/agents/{name}.md` | Running the protocol in its own context and returning a fixed-format report |

Rules:

1. **The protocol lives once**, in `skills/{name}/references/*.md`, with an explicit **output contract** (report format). The subagent files never duplicate it. They only say "read the protocol, follow it, return the report".
2. **The skill must work without the subagent.** Its delegation step always has an inline fallback: "no subagent → follow `references/…` yourself".
3. **The skill passes the absolute protocol path** in the delegation prompt (its base directory + `references/…`). The subagent resolves the protocol in this order:
   1. the path from the prompt;
   2. `${CLAUDE_PLUGIN_ROOT}/skills/{name}/references/…` (Claude Code substitutes this in plugin agents);
   3. a Glob over the standard skill dirs.

   If it finds nothing, it stops and says how to install the skill.
4. **Workers are read-only.** Claude Code: `tools:` without Edit/Write. OpenCode: `permissions` with `edit` denied and destructive shell commands denied. Write and destructive actions stay in the main conversation, where the user can approve them.
5. **Treat the report as evidence, not truth.** The skill spot-checks the rows it will act on before building the plan.
6. **Descriptions must not compete.** The skill's description targets the full task. The subagent's description says it is a *detection/report worker* used when the skill delegates, or when the user wants only a report.

OpenCode agent frontmatter uses **V2**: `mode: subagent` and an ordered `permissions:` list (`action` / `resource` / `effect`, last match wins). Actions are `shell` (not `bash`), `edit`, and `subagent` (not `task`). Don't use `temperature`, `tools`, or `permission`. Check parsing with `opencode debug agents`.

## Context Efficiency

- Keep `SKILL.md` under ~500 lines and push reference material into `references/`.
- Use **progressive disclosure**: link from `SKILL.md` to supporting files, one level deep.
- Prefer **scripts over inline code**. Script execution doesn't consume context, only its output does.
- Delegate heavy, read-only phases to a companion subagent (see above).

## Script Requirements

- Shebang: `#!/usr/bin/env bash`, `#!/usr/bin/env python3`, etc.
- Bash: `set -euo pipefail`
- Status messages → stderr (`echo "..." >&2`)
- Machine-readable output → stdout (JSON when possible)
- Trap cleanup of temp files

## Adding a New Skill

1. Create `skills/{skill-name}/SKILL.md` with valid frontmatter.
2. Add helper scripts under `skills/{skill-name}/scripts/` if needed.
3. Register it in `.claude-plugin/marketplace.json`, as a new plugin entry or added to an existing plugin's `skills` array.
4. Add an entry to **Available skills** in the root `README.md`.
5. Run `scripts/validate.sh`.
6. Test locally:

   ```bash
   npx skills add /path/to/this/repo --list
   claude plugin validate .
   ```

### Adding a companion subagent

1. Move the heavy protocol into `skills/{name}/references/<protocol>.md` and end it with an output contract.
2. Add a delegation step to `SKILL.md`, with an inline fallback.
3. Create `agents/{name}.md` (Claude Code) and/or `opencode/agents/{name}.md` (OpenCode V2), following the rules above.
4. Add `"agents": ["./agents/{name}.md"]` to the plugin entry in `marketplace.json`.
5. Run `scripts/validate.sh`. It checks that every `…/references/*.md` an agent mentions exists.

## Versioning

Don't add version fields to make updates work:

- `npx skills` detects updates by the **git tree SHA of each skill folder**. Any committed change inside `skills/{name}/` is an update for that skill only.
- Claude Code plugins without a `version` use the **commit SHA** as the version. **Do not add `"version"`** to `marketplace.json` entries or a `plugin.json`: it would pin users until someone remembers to bump it.
- Use git tags (`vX.Y.Z`) only to offer stable pins: `npx skills add owner/repo@vX.Y.Z`.

## Distribution

```bash
# npx skills (any agent)
npx skills add https://github.com/diegofcornejo/random-ai-skills
npx skills add https://github.com/diegofcornejo/random-ai-skills --skill {skill-name}
npx skills add https://github.com/diegofcornejo/random-ai-skills --list

# Claude Code plugin (skill + subagent together)
/plugin marketplace add diegofcornejo/random-ai-skills
/plugin install {plugin-name}@random-ai-skills

# Agents/commands for OpenCode or plugin-less Claude Code
scripts/install-agents.sh
```

`npx skills` discovers skills under `skills/` and also those declared in `.claude-plugin/marketplace.json`, and it groups them by plugin in `--list`.

## Security

- Never commit secrets. Configs reference them as environment variables (`{env:VAR}` in OpenCode).
- `scripts/validate.sh` greps for common key formats. It is a tripwire, not a guarantee.

## References

- [agentskills.io](https://agentskills.io/): skills format spec
- [`skills` npm package](https://www.npmjs.com/package/skills): installer CLI
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents) · [plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [OpenCode agents](https://opencode.ai/docs/agents/) · [OpenCode skills](https://opencode.ai/docs/skills/)
