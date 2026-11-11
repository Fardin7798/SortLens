# Tasks — the work queue

One file per task, numbered in build order. A coding agent gets exactly one task:

> Read `AGENTS.md`, then do `docs/tasks/03-date-sort.md`. Stop when its "Done when" list is all true.

## Status
| # | Task | Status |
|---|------|--------|
| 01 | Importers (Takeout + folder → SQLite) | done |
| 02 | [Full Takeout metadata](02-takeout-metadata.md) | done |
| 03 | [Date sort](03-date-sort.md) | todo |

Later tasks (duplicates, solo category, live progress, review + undo, Windows setup) get a file when their turn comes, so they follow what was really built.

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
