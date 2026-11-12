# AGENTS.md — rules for any coding agent on SortLens

Claude Code, Cursor, Codex, Copilot and humans all follow this one file.

## What this is
Local-first, offline photo organizer. Sources: Google Takeout export (main focus) and plain laptop folders, through ONE pipeline.

## Hard rules (never break)
1. Never delete a file. There is no delete code in SortLens (a test checks). "Delete" = move into the location's `SortLens Trash`. Scanning is read-only; zips are never changed.
2. A file moves only through an approved plan (`backend/app/core/plans.py`, confirm code) and `backend/app/core/safety.py` `move_file`, which writes the undo log first. See `docs/SAFETY.md`.
3. Fully offline at runtime. No cloud APIs, no telemetry.
4. Must run on a low-end CPU laptop (i3, 8 GB, no GPU, Windows 11): small batches, resumable, no GPU-only libs.
5. Real data only. Missing date/location stays missing and is shown as missing. Never invent a value.

## How to do a task
1. Read the task file in `docs/tasks/` (or the GitHub issue that links to it). Do only what it says. "Out of scope" means do not touch.
2. Read the docs it lists (`docs/ARCHITECTURE.md`, `docs/TAKEOUT.md`, ...).
3. Write code + tests. Every new behavior gets a test. Tests build their own fake data in `tmp_path`; never use real user photos.
4. Run `scripts/check.sh` (Linux/macOS) or `scripts\check.ps1` (Windows). It must pass.
5. Tick the task's box in `docs/ROADMAP.md`, set the task file's `Status: done`.
6. Commit on branch `dev` (or a `task/NN-name` branch). Open a PR to `main`. Never push to `main`.
7. Stop and report: what changed, which files, check output. Do not start the next task.

If the task file is unclear or a hard rule would be broken, stop and ask. Do not guess.

## Layout
- `backend/app/core` settings + safety gate
- `backend/app/importers` Takeout + folder readers (produce the same `MediaRecord`)
- `backend/app/pipeline` steps: date, hash, near-dup, faces; each step resumable on its own
- `backend/app/db` SQLite store (`store.py` owns the schema)
- `backend/app/api` FastAPI routes + live progress (SSE)
- `backend/app/cli.py` command line (`sortlens ...`)
- No frontend yet: the UI is built last, after the backend is complete. Do not add one unless a task says so.
- `docs/tasks/` one file per task, the work queue

## Checks (all in `scripts/check.sh`)
- backend: `ruff check . && ruff format --check . && mypy app && pytest -q`

## Code style
- Python 3.12, type hints everywhere, small functions, no new heavy dependency without saying why in the PR.
- Pipeline steps take a `sqlite3.Connection`, work in batches (default 50), commit per batch, and can be stopped and re-run safely.
- Schema changes: add columns with `ALTER TABLE ... ADD COLUMN` guarded in `store.connect()` so old databases keep working.

## Git
- Agents work on `dev` or `task/NN-name`. Merge to `main` only on the owner's clear yes.
- Commit author: `Fardin7798 <shaikhfardin206@gmail.com>`.
- One task = one PR. Commit message: `Task NN: <short summary>`.
