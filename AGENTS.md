# AGENTS.md

## Skills

Repo-local skills live under `skills/`.

Available skills:
- `commit-messages`: use for creating, amending, or rewording git
  commit messages. File: `skills/commit-messages/SKILL.md`

If a task clearly matches a listed skill, read its `SKILL.md` and use
it for that turn.

## Misc

- Use `uv` for running python and tooling.
- After making edits:
  - Run `basedpyright` and fix issues.
  - Run `ruff check` and fix issues.
  - Run `ruff format`.
