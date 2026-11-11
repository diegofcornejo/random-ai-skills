# CLAUDE.md

Guidance for Claude Code when working in this repository.

> Most authoring rules live in [AGENTS.md](AGENTS.md). This file only adds Claude-Code-specific notes.

## Repo Purpose

Personal collection of [Agent Skills](https://agentskills.io/) plus companion subagents and commands. Skills (`skills/{skill-name}/`) are distributed via `npx skills` and as Claude Code plugins (`.claude-plugin/marketplace.json`). Subagents live in `agents/` (Claude Code) and `opencode/agents/` (OpenCode).

## Working Conventions

- **Editing a skill**: modify files under `skills/{skill-name}/`. Keep `SKILL.md` under ~500 lines and push detail into sibling files (`references/`, `analysis-levels.md`, etc.).
- **Adding a skill**: follow the checklist in [AGENTS.md](AGENTS.md#adding-a-new-skill). Always register it in `.claude-plugin/marketplace.json` and update **Available skills** in the root `README.md`.
- **Skill + subagent**: follow [the pattern in AGENTS.md](AGENTS.md#the-skill--subagent-pattern). The protocol lives once in `references/`, and agents only point to it.
- **No `version` fields**: updates are detected by git tree/commit SHA. See [AGENTS.md#versioning](AGENTS.md#versioning).
- **Before pushing**: run `scripts/validate.sh`.
- **Frontmatter** — `name:` MUST match directory name. The CLI matches `--skill <name>` against the directory.
- **Trigger phrases** — the `description:` is the only thing loaded into context at startup. Be specific. Include filenames, commands, keywords the user is likely to type.

## Local Testing

Install from a local clone (no GitHub round-trip):

```bash
npx skills add file:///Users/diego/personal/skills --skill {skill-name} -y
```

Install from GitHub (after pushing):

```bash
npx skills add https://github.com/diegofcornejo/skills --skill {skill-name} -y
```

Load the whole repo as a session-only Claude Code plugin (skills + subagents, namespaced `skills:`):

```bash
claude --plugin-dir /Users/diego/personal/skills
claude plugin validate /Users/diego/personal/skills
```

List skills the CLI sees in the repo:

```bash
npx skills add https://github.com/diegofcornejo/skills --list
```

## Things to Avoid

- Don't rename a skill directory without also updating `name:` in `SKILL.md` and the README entry — installation will silently use the wrong name.
- Don't commit large binaries or generated `.zip` packages — the CLI installs from source.
- Don't put trigger phrases only in the body — the body is not loaded until the skill activates.

## Useful Commands

```bash
# scaffold a new skill
npx skills init {skill-name}

# list installed skills (project)
npx skills list

# list installed skills (global)
npx skills list -g
```
