# AGENTS.md

Guidance for AI coding agents (Claude Code, Cursor, Copilot, Codex, Gemini CLI, etc.) working in this repository.

## Repository Overview

A personal collection of [Agent Skills](https://agentskills.io/). Each skill lives under `skills/{skill-name}/` and is distributed via the [`npx skills`](https://www.npmjs.com/package/skills) CLI.

## Directory Structure

```
skills/
  {skill-name}/           # kebab-case
    SKILL.md              # REQUIRED — frontmatter + instructions
    README.md             # optional — human-facing docs
    scripts/              # optional — helper scripts (.sh, .py, .ts)
    examples/             # optional — sample inputs/outputs
    references/           # optional — extra docs loaded on demand
```

## Naming Conventions

- **Skill directory**: `kebab-case` (e.g. `deepsec-findings-analyzer`)
- **`SKILL.md`**: exact filename, uppercase `.md` extension
- **Scripts**: `kebab-case.{sh,py,ts}`
- Directory name MUST match the `name:` field in `SKILL.md` frontmatter — the `npx skills add --skill <name>` flag matches against directory name.

## SKILL.md Format

```markdown
---
name: {skill-name}
description: {One sentence. Include trigger phrases the agent will pattern-match on.}
---

# {Skill Title}

Brief description.

## When to use this skill

- Trigger condition 1
- Trigger condition 2

## How it works

1. Step
2. Step

## Usage

Example invocations / commands.

## Output

What the user sees.
```

### Frontmatter rules

- `name` — must match directory name, kebab-case
- `description` — one sentence, must include concrete trigger phrases (file names, commands, keywords) so the agent picks the skill up at the right moment

## Context Efficiency

Skills are loaded on demand: only `name` + `description` are loaded at startup. The full `SKILL.md` loads only when the agent decides the skill is relevant.

- Keep `SKILL.md` under ~500 lines — push reference material into sibling files
- Use **progressive disclosure**: link from `SKILL.md` to supporting files (one level deep)
- Prefer **scripts over inline code** — script execution does not consume context, only its output does
- Write **specific descriptions** — vague descriptions lead to missed activations

## Script Requirements

- Shebang: `#!/usr/bin/env bash`, `#!/usr/bin/env python3`, etc.
- Bash: `set -euo pipefail`
- Status messages → stderr (`echo "..." >&2`)
- Machine-readable output → stdout (JSON when possible)
- Trap cleanup of temp files

## Adding a New Skill

1. Create `skills/{skill-name}/SKILL.md` with valid frontmatter
2. Add helper scripts under `skills/{skill-name}/scripts/` if needed
3. Add an entry to the **Available Skills** section in the root `README.md`
4. Test installation locally:

   ```bash
   npx skills add https://github.com/diegofcornejo/skills --skill {skill-name} -y
   ```

## Distribution

End users install via:

```bash
# whole repo
npx skills add https://github.com/diegofcornejo/skills

# single skill
npx skills add https://github.com/diegofcornejo/skills --skill {skill-name}

# list available skills without installing
npx skills add https://github.com/diegofcornejo/skills --list
```

The CLI clones the repo, scans for `SKILL.md` files under `skills/`, and symlinks (or copies with `--copy`) the matching skill directories into the agent's skills folder (e.g. `~/.claude/skills/`, `.cursor/rules/`, etc.).

## References

- [agentskills.io](https://agentskills.io/) — skills format spec
- [`skills` npm package](https://www.npmjs.com/package/skills) — installer CLI
- [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) — reference repo for layout
