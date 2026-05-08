# skills

A collection of [Agent Skills](https://agentskills.io/) by [@diegofcornejo](https://github.com/diegofcornejo) for Claude Code, Claude.ai, Cursor, Copilot, and any agent that supports the skills format.

## Installation

Install the whole collection:

```bash
npx skills add https://github.com/diegofcornejo/skills
```

Install a single skill:

```bash
npx skills add https://github.com/diegofcornejo/skills --skill deepsec-findings-analyzer
```

Install globally (user-level) with all agents:

```bash
npx skills add https://github.com/diegofcornejo/skills --skill deepsec-findings-analyzer -g -a '*' -y
```

> Requires the [`skills`](https://www.npmjs.com/package/skills) CLI (auto-fetched by `npx`).

## Available Skills

### [deepsec-findings-analyzer](skills/deepsec-findings-analyzer)

Triage security findings from a [deepsec](https://github.com/vercel-labs/deepsec) scan. Groups findings by root cause, prioritizes by impact and effort, and generates ticket-ready drafts.

**Use when:**

- You ran `deepsec export --format json` and want help understanding the findings
- You need to prioritize fixes for a `findings.json` file
- You want to convert findings into copy-paste tickets for your tracker

## Repository Layout

```
skills/
  {skill-name}/        # one directory per skill (kebab-case)
    SKILL.md           # required: skill definition (frontmatter + body)
    README.md          # optional: human-facing docs
    scripts/           # optional: helper scripts
    examples/          # optional: sample inputs/outputs
    references/        # optional: extra docs loaded on demand
```

The `npx skills` CLI auto-discovers any directory under `skills/` that contains a `SKILL.md`.

## Contributing

See [AGENTS.md](AGENTS.md) for skill authoring conventions and [CLAUDE.md](CLAUDE.md) for guidance when working on this repo with Claude Code.

## License

MIT — see individual skills for their own licenses where applicable.
