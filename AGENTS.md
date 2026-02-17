# dead-drop-teams — Agent Instructions

Multi-agent coordination MCP server. SQLite message passing with role-based agents and auto-CC to lead.

Any AI coding tool that supports MCP can participate: Claude Code, Codex CLI, OpenCode, Gemini, or anything that speaks the protocol.

## Quick Reference

- **Server:** `src/dead_drop/server.py`
- **Architecture:** `docs/ARCHITECTURE.md` — schema, CC protocol, agent lifecycle, inbox discipline
- **Protocol:** `docs/PROTOCOL.md` — agent-facing rules (register, message format, queuing)
- **Database:** `~/.dead-drop/messages.db` (override with `DEAD_DROP_DB_PATH`)

## Tools

| Tool | Purpose |
|------|---------|
| `register` | Sign in with name, role, description |
| `send` | Message an agent (auto-CCs lead) |
| `check_inbox` | Read unread messages |
| `who` | List agents + last seen |
| `get_history` | Last N messages (post-compaction catch-up) |

## Codex Checklist

Use this when running as Codex in a pull-based chat session:

1. Start inbox poller in a side terminal:
   ```bash
   ~/.dead-drop/poll_inbox.sh codex 60
   ```
2. Keep working normally in Codex.
3. If poller prints unread messages, run `check_inbox` immediately.
4. Reply with `send` and always CC the lead.
5. Treat poller output as a trigger only; `check_inbox` is the source of truth.

See also: [`README.md`](README.md) and [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Roles

Roles describe function, not which AI model runs them. Any model can fill any role.

| Role | Function | Lifecycle | Profile |
|------|----------|-----------|---------|
| `lead` | Coordinates, reviews, routes tasks | Persistent | [`docs/roles/lead.md`](docs/roles/lead.md) |
| `researcher` | Reads source, finds bugs, writes analysis | Persistent | [`docs/roles/researcher.md`](docs/roles/researcher.md) |
| `coder` | Writes code from specific instructions | Ephemeral | [`docs/roles/coder.md`](docs/roles/coder.md) |
| `builder` | Builds, runs tests, executes commands | Ephemeral | [`docs/roles/builder.md`](docs/roles/builder.md) |

Role profiles are deployed to `~/.dead-drop/roles/` by `scripts/install.sh`.

## Naming Convention

`<agent-name>` — pick something descriptive. Examples:
- `claude-lead`, `codex-coder`, `gemini-researcher`, `opencode-builder`

## Rules

- Server code only — no project-specific knowledge in this repo
- Migrations in `init_db()` must be additive (ALTER TABLE ADD COLUMN, never DROP)
- Test with `python -m dead_drop.server` before committing

## Dev

```bash
cd ~/projects/dead-drop-teams
uv venv && source .venv/bin/activate && uv pip install -e .
```
