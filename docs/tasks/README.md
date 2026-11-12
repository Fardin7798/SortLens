# Tasks — the work queue

One file per task, numbered in build order. A coding agent gets exactly one task:

> Read `AGENTS.md`, then do `docs/tasks/NN-name.md`. Stop when its "Done when" list is all true.

## Status
| # | Task | Status |
|---|------|--------|
| 01 | Importers (Takeout + folder → SQLite) | done |
| 02 | [Full Takeout metadata](02-takeout-metadata.md) | done |
| 03 | [Solo list](03-solo-list.md) | done |
| 04 | [Date sort](04-date-sort.md) | done |
| 05 | [Duplicates](05-duplicates.md) | done |
| 06 | [Live progress (jobs + SSE)](06-live-progress.md) | done |
| 07 | [Review + undo](07-review-undo.md) | done |
| 08 | [Windows one-command setup](08-windows-setup.md) | review |

After 08 the v1 backend is complete. Next: the real Takeout test, then the UI (each gets a task file when its turn comes).

## Template for a new task
```markdown
# Task NN: <name>
Status: todo
Roadmap line: <exact line in docs/ROADMAP.md>

## Why
<one or two lines: what the user gets>

## Read first
<docs and files>

## Build
<numbered, concrete: files, functions, columns, CLI/API>

## Rules for this task
<edge cases, what must never happen>

## Out of scope
<what not to touch>

## Done when
- [ ] ...
- [ ] `scripts/check.sh` passes
- [ ] ROADMAP ticked, this file `Status: done`
```
