# Task Tracking — Filesystem as Database

Tasks are tracked as files and folders in `.dead-drop/tasks/`. No database, no special tools — agents navigate tasks with `ls`, `cat`, and `grep`.

## Directory Structure

```
<project-root>/.dead-drop/
├── tasks/
│   ├── BUG-001/
│   │   ├── task.md        # description (immutable after creation)
│   │   ├── status         # one word: open | assigned | in_progress | fixed | verified | closed
│   │   ├── assigned       # agent name, empty file if unassigned
│   │   └── result.md      # what was done, files changed, before/after
│   ├── BUG-002/
│   │   └── ...
│   └── FEAT-001/
│       └── ...
├── <agent-name>/          # agent workspace (existing convention)
│   └── ...
```

## Task Lifecycle

```
open → assigned → in_progress → fixed → verified → closed
```

1. **Lead creates** the task folder and writes `task.md` + sets `status` to `open`
2. **Lead assigns** by writing agent name to `assigned` and setting `status` to `assigned`, then sends ONE message to the agent referencing the task folder
3. **Agent sets** `status` to `in_progress` when starting work
4. **Agent writes** `result.md` when done, sets `status` to `fixed`
5. **Builder verifies** (build + test), sets `status` to `verified`
6. **Lead reviews** and sets `status` to `closed`

## File Formats

### task.md

```markdown
# BUG-001: Short title

**Severity:** high | medium | low
**Files:** src/foo.cpp:120-150, include/bar.h

## Problem
What's broken and why.

## Approach
How to fix it. Which pattern to follow.

## Constraints
What NOT to touch.
```

### status

Single word, no newline. One of: `open`, `assigned`, `in_progress`, `fixed`, `verified`, `closed`.

```
in_progress
```

### assigned

Agent name, or empty file if unassigned.

```
gemini-cli-agent
```

### result.md

```markdown
# Result: BUG-001

**Fixed by:** gemini-cli-agent
**Files changed:** src/foo.cpp:125, src/foo.cpp:130

## Changes
- Line 125: changed `x` to `y` because ...
- Line 130: added null check for ...

## Notes
Anything the reviewer should know.
```

## Agent Operations

### Find open tasks
```bash
grep -rl "open" .dead-drop/tasks/*/status
```

### Find my tasks
```bash
grep -rl "my-agent-name" .dead-drop/tasks/*/assigned
```

### Check a task's state
```bash
cat .dead-drop/tasks/BUG-001/status
cat .dead-drop/tasks/BUG-001/assigned
```

### Claim and start
```bash
echo "my-agent-name" > .dead-drop/tasks/BUG-001/assigned
echo "in_progress" > .dead-drop/tasks/BUG-001/status
```

## Adversarial Tasks

For recurring or high-stakes bugs, lead sends the same task to multiple agents independently. Each agent writes their findings to a **named result file** in the task folder:

```
.dead-drop/tasks/BUG-011/
├── task.md                      # shared spec (read-only)
├── status                       # "investigating"
├── assigned                     # "adversarial" or comma-separated agent names
├── result_codex.md              # codex's independent findings
├── result_gemini-cli-agent.md   # gemini's independent findings
├── result_sonnet.md             # sonnet's independent findings
├── result_haiku.md              # even haiku gets a shot
└── result.md                    # lead's final synthesis after cross-examination
```

### Rules for adversarial tasks
- **Agents write `result_<agent-name>.md`**, not `result.md`
- **Do NOT read other agents' result files** until lead says to (no peeking)
- **Lead writes `result.md`** after comparing all findings and cross-examining
- Status flow: `open` → `investigating` → `cross-exam` → `fixed` → `verified` → `closed`

## Rules

1. **One task per folder.** Folder name is the task ID (e.g. `BUG-001`, `FEAT-003`).
2. **task.md is immutable** after creation. If requirements change, lead adds a `revision.md` or creates a new task.
3. **Only the assigned agent writes result.md** (or `result_<name>.md` for adversarial tasks). Anyone can read.
4. **Only lead creates and closes tasks.**
5. **Agents update their own status.** Don't update another agent's task status (except lead).
6. **Message references folder, not contents.** When assigning via dead-drop, say "see `.dead-drop/tasks/BUG-001/task.md`" — don't paste the full spec into the message.
7. **Prefixes:** `BUG-` for bugs, `FEAT-` for features, `TASK-` for general work.
