# Dead Drop Protocol v1.0

Shared MCP server for cross-agent communication. Any number of agents (Claude, Gemini, or others) can connect.

## Agent Naming

The lead registers all agents on session start and chooses names that make ownership clear. There is no enforced convention — the lead decides.

Examples:
- `claude-opus-orange` (lead), `sonnet-orange` (coder), `haiku-orange` (builder) — color = team
- `gemini-benchmarker` — persistent researcher, self-registers

## Tools

| Tool | Args | Purpose |
|------|------|---------|
| `register` | `agent_name` | Register yourself on connect |
| `send` | `from, to, message` | Send to agent name or `"all"` for broadcast. **Blocked if you have unread messages.** |
| `check_inbox` | `agent_name` | Get unread messages, marks them read |
| `get_history` | `count` | Last N messages (for post-compaction catch-up) |
| `who` | — | List registered agents + last seen + last inbox check |

## Rules

1. **Lead registers all agents on session start.** Lead pre-registers its coder and builder slots, then spawns agents into them. Persistent agents (researcher) may self-register.
2. **Check inbox after completing a task.** When you finish a task, call `check_inbox`. If messages waiting, process them before starting the next task.
3. **Structured messages.** Format: what you did, what you found, what the recipient should do next.
4. **Broadcast sparingly.** Only for things every agent needs immediately.
5. **After context compaction**, call `get_history(10)` to restore cross-agent state.
6. **Don't poll in a loop yourself.** One `check_inbox` per task completion.
7. **Idle monitoring.** If you have no immediate work, delegate a subagent to poll `check_inbox` every 20 seconds and notify you when a message arrives. Kill the monitor when you start a new task.

### Codex Inbox Monitoring (Pull-Based Sessions)

Codex sessions are pull-based. The server cannot inject an unsolicited chat turn when a new message arrives.

Use this workflow:

1. Run a side-terminal poller:
   ```bash
   ~/.dead-drop/poll_inbox.sh codex 60
   ```
2. When poller output shows unread messages, immediately call `check_inbox` from Codex.
3. Process and reply via `send` (with `cc` to lead).

Important:
- Poller output is a trigger only; it does not mark messages read.
- Poller output does not auto-inject content into the active Codex session.
- `check_inbox` remains the source of truth for message state.

## Filesystem as Database

The `.dead-drop/` directory is the shared state for all agents. Tasks, progress, and results are tracked as files and folders — no database, no special tools. Agents navigate with `ls`, `cat`, and `grep`.

### Directory Convention

```
<project-root>/.dead-drop/
├── tasks/                 # task tracking (filesystem as database)
│   ├── BUG-001/
│   │   ├── task.md        # description (immutable)
│   │   ├── status         # open | assigned | in_progress | fixed | verified | closed
│   │   ├── assigned       # agent name
│   │   └── result.md      # what was done
│   └── ...
├── <agent-name>/          # each agent owns their folder
│   ├── <task-slug>.log    # build/test output
│   └── ...
└── .gitignore
```

**Full task tracking spec:** [`docs/tasks.md`](tasks.md) — task lifecycle, file formats, templates, and rules.

### Agent Folders

- **Location:** `<project-root>/.dead-drop/<your-agent-name>/`
- **Folder = registered name.** `gemini-benchmarker` writes to `.dead-drop/gemini-benchmarker/`.
- **Create your folder on first task** if it doesn't exist.
- **Write only to your own folder.** Read anyone's.
- **Naming:** `<task-slug>.log` — e.g. `bug013-fix.log`, `intel-ops-test.log`
- **Writer:** Pipe output with `tee .dead-drop/<your-name>/<task>.log` or write directly
- **Reader:** Other agents `tail` the file to watch live progress

### Task Folders

- **Lead creates** task folders in `.dead-drop/tasks/<TASK-ID>/`
- **Agents read** `task.md` for specs, update `status` and write `result.md`
- **Messages reference folders** — say "see `.dead-drop/tasks/BUG-001/task.md`", don't paste full specs into messages
- **One task per folder, one folder per task.**

### Progress Updates

- **Don't send progress updates via dead drop messages** — write to your agent folder log file.
- **When done:** Send ONE summary message via dead drop with pass/fail. Reference the task folder and log file.

### Why not /tmp/?

Some agents (e.g. Gemini) are sandboxed to their workspace. Project-local `.dead-drop/` is accessible to all agents working in the repo.

## Roles

Four roles define what agents do. Any model can fill any role.

| Role | Lifecycle | Function |
|------|-----------|----------|
| `lead` | Persistent | Coordinates, reviews, routes tasks |
| `researcher` | Persistent | Reads source, finds bugs, writes analysis |
| `coder` | Ephemeral | Writes code from specific instructions |
| `builder` | Ephemeral | Builds, runs tests, executes commands |

**Detailed role profiles:** `docs/roles/` in the repo, deployed to `~/.dead-drop/roles/` by `scripts/install.sh`.

Agents receive their role profile automatically in the `register()` response — no file reads needed.

Each profile covers: responsibility, input/output, communication rules, and boundaries.

## Agent Routing

The lead agent is the router. All other agents report to lead. The human manages one window.

### Lead subagents

The lead spawns two persistent subagents on session start using its own model family:

| Slot | Model | Role | Function |
|------|-------|------|----------|
| `haiku-<team>` | Haiku | `builder` | Builds, runs tests, executes commands |
| `sonnet-<team>` | Sonnet | `coder` | Light coding tasks, quick fixes |

- Lead pre-registers both slots and spawns them via Task tool.
- These are **always available** — lead doesn't need to ask human to start them.
- External agents (Gemini, Codex, etc.) are registered separately by lead or self-register.

**Token leash:** When spawning subagents via Task tool, ALWAYS set `max_turns` to cap how many rounds they get. Subagents (especially sonnet) will burn tokens endlessly if not leashed.

| Task type | max_turns |
|-----------|-----------|
| Investigation / research | 30 |
| Code review | 20 |
| Build & test | 15 |
| Quick fix / small edit | 10 |

Also include in the agent's prompt: **"You have a hard limit of N tool calls. Write your result file FIRST, then send your message. Do not spend more than half your budget on reading — start writing findings early."**

### CC discipline

**All agent-to-agent messages must CC the lead.** Use the `cc` parameter on `send()`.

- Reviewer finds issue → sends fix to coder, CC lead
- Coder finishes task → reports to lead, CC reviewer
- Builder finishes build → reports to lead, CC coder

This keeps lead in the loop without being a bottleneck. Lead can intervene if needed but doesn't have to route every message.

### Ephemeral agent spawn pattern
1. Lead pre-registers the agent slot (name, role)
2. Lead sends task message to the agent name via dead-drop
3. Lead spawns the agent — agent re-registers (gets onboarding), checks inbox, finds task waiting
4. Agent executes, reports back via dead-drop (CC lead), dies
5. Slot stays registered. Next task = new spawn into same slot.

### Queuing discipline
- One task per message per agent. Wait for completion before sending next.
- Never stack messages — leads to conflicts and planning loops (especially Gemini).

## Pre-Flight Setup

Before any agent touches code, the lead runs these setup steps. This is non-negotiable — agents without context burn tokens re-discovering what the codebase looks like.

### Checklist

1. **Dissect the codebase** — run `scripts/dissect.py <project_root>` to generate `.dead-drop/CODE_MAP.md`. This extracts every function, struct, class with line ranges using tree-sitter. Agents read the map, not the files.

2. **Define code ownership zones** — create `.dead-drop/CODE_OWNERS.md` with:
   - Full directory tree with line counts
   - Zone assignments (agent → files)
   - Key architectural facts (so agents don't re-discover them)
   - Rules for cross-zone communication

3. **Register agents** — pre-register all agent slots with names, roles, descriptions.

4. **Verify tooling** — ensure tree-sitter and language grammars are installed:
   ```
   pip3 install tree-sitter tree-sitter-c tree-sitter-cpp tree-sitter-python
   ```

5. **Create task folders** — set up `.dead-drop/tasks/` with initial task definitions.

6. **Broadcast onboarding** — send a message to `all` with:
   - Link to CODE_MAP.md
   - Link to CODE_OWNERS.md
   - Current task assignments
   - Any project-specific rules

### Why this matters

Without pre-flight, the first 30% of every agent's context gets burned on `find`, `ls`, `grep` to understand what they're working on. With pre-flight, they start at the function they need to change.

## Code Ownership Zones

Each project should define a `CODE_OWNERS.md` in `.dead-drop/` that assigns code sections to agents. This prevents context blowout from agents reading the entire codebase on every task.

### Rules

1. **Lead creates `CODE_OWNERS.md`** at project start, mapping file paths to agent names.
2. **Agents ONLY read files in their zone.** If you need info from another zone, send a message to the owner asking for the specific detail (file, line, behavior).
3. **Cross-zone changes require approval** from both zone owners via dead-drop.
4. **Zone owners are the experts.** When a task touches their files, route it to them. Don't send a scheduler task to the Metal kernel expert.
5. **Zone file format:**
```markdown
## agent-name — Zone Label
**Files:**
- `path/to/file.cpp` — what it does
- `path/to/dir/` — what it contains

**You are the expert on:** one-line summary of domain knowledge
```

### Why this matters

Agents have finite context windows. Reading a 5000-line file outside their zone burns 20% of their budget before they even start working. Code ownership keeps agents focused and prevents the "read everything, understand nothing" pattern.

## Debug Logging Standards

When adding debug instrumentation to code, follow these rules:

1. **Never log inside hot loops.** A loop that runs 100+ times should NOT have `fprintf`/`GGML_LOG_DEBUG` on every iteration. Instead:
   - Add a counter before the loop
   - Increment inside the loop
   - Print the summary ONCE after the loop exits (e.g. `"computed %d splits across %d backends"`)
2. **One-shot context on entry.** Print parameters/config once at function entry, not repeatedly.
3. **Always remove or gate debug logs before marking a task fixed.** If logs are needed for verification, use `GGML_LOG_DEBUG` (compile-time gated) not `fprintf(stderr, ...)`.
4. **Tag debug lines.** Use `// AIDBG` comment so they can be bulk-found and removed with `grep AIDBG`.

## Architecture

- Server: `~/.dead-drop/server/main.py` (stdio MCP)
- Database: `~/.dead-drop/messages.db` (SQLite)
- Tables: `agents` (name, registered_at, last_seen, last_inbox_check), `messages` (id, from_agent, to_agent, content, timestamp, read_flag), `broadcast_reads` (agent_name, message_id)
