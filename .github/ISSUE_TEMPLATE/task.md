---
name: Task
about: One unit of work for a coding agent
title: "Task NN: "
labels: task
---
Task file: `docs/tasks/NN-name.md`

Agent prompt:
> Read `AGENTS.md`, then do `docs/tasks/NN-name.md`. Work on branch `dev` (or `task/NN-name`). Stop when its "Done when" list is all true and `scripts/check.sh` passes. Never push to `main`.
