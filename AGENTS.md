# AGENTS.md — rules for any coding agent on SortLens

## What this is
Local-first, offline photo organizer. Sources: Google Takeout export (main focus) and plain laptop folders, through ONE pipeline.

## Hard rules (never break)
1. Never delete, move, rename or modify a user's photo, zip or JSON file. Scanning is read-only.
2. Every move/delete goes through `backend/app/core/safety.py`: needs an explicit user approval id, writes the undo log first.
3. Fully offline at runtime. No cloud APIs, no telemetry.
4. Must run on a low-end CPU laptop (i3, 8 GB, no GPU): small batches, resumable, no GPU-only libs.
5. Real data only. Missing date/location stays missing and is shown as missing.

## Layout
- `backend/app/core` settings + safety gate
- `backend/app/importers` Takeout + folder readers (produce the same record)
- `backend/app/pipeline` steps: date, hash, near-dup, faces; each step resumable on its own
- `backend/app/db` SQLite store
- `backend/app/api` FastAPI routes + live progress (SSE)
- `frontend/` Next.js local UI; `src/lib/api.ts` is the only place with the API base URL

## Checks before every push
- backend: `ruff check . && ruff format --check . && mypy app && pytest`
- frontend: `npm run lint && npm run build`

## Git
Agents work on branch `dev`. Merge to `main` only on the owner's clear yes.
