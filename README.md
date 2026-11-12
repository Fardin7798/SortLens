# SortLens

Local-first, offline photo organizer. Point it at a **Google Takeout** export or any **laptop folder**, and it sorts your photos by date, finds duplicates, and collects photos where you are alone, while a local web page shows live progress.

> **Safety promise:** SortLens never deletes or moves your photos on its own. It only categorizes. Any move or delete happens only after it shows you the full list and you say yes, and every action can be undone.

## Status
Early development (v0.1 skeleton). See `docs/ROADMAP.md`.

## Runs on
Windows / Linux / macOS, CPU only (built and tested for a 12th-gen i3 laptop, no GPU), fully offline.

## Quick start (dev)
```bash
cd backend
uv venv && uv pip install -e ".[dev]"
uv run sortlens serve        # http://127.0.0.1:8765/api/health
```
Import photos (read-only, safe to re-run; it resumes):
```bash
uv run sortlens import-takeout takeout-001.zip takeout-002.zip   # or an extracted Takeout folder
uv run sortlens import-folder "D:/Photos"
uv run sortlens stats
uv run sortlens dupes     # duplicate lists, then: sortlens dupes-show 1
uv run sortlens dates     # best taken-at date per file: Takeout > EXIF > file name > file time
```
Solo list: photos where one person is alone (reads only; nothing is moved):
```bash
uv pip install -e ".[faces]"            # OpenCV, CPU only
uv run sortlens models download         # two small ONNX face models, once (~39 MB, SHA-256 checked)
uv run sortlens solo "Fardin" --photo me.jpg      # add --tagged-only to check only Takeout tags
uv run sortlens solo-show 1 --bucket solo         # solo | group | check
```
Local API (`sortlens serve`, 127.0.0.1 only): start a long step and watch it live.
```text
POST /api/jobs   {"kind": "import_takeout", "params": {"paths": ["D:/takeout-001.zip"]}}
                 kinds: import_takeout | import_folder | dates | dupes | solo
GET  /api/jobs/{id}/events   live progress (Server-Sent Events), ends with an `end` event
POST /api/jobs/{id}/stop     stops at the next batch; run again to resume
```
Review (the only way a file moves; nothing is ever deleted):
```bash
uv run sortlens plan-trash-dupes 1          # duplicate extras -> SortLens Trash (a plan, nothing moves)
uv run sortlens plan-move-solo 2 --to "Fardin akela"
uv run sortlens plan-show 3                 # full list + confirm code
uv run sortlens apply 3 --code <code>       # then, if needed: sortlens undo 3 --code <code>
```
API: `POST /api/plans`, `GET /api/plans/{id}`, `POST /api/plans/{id}/apply|undo` with `{"code": ...}`.

A one-command setup script comes in v1.

## Docs
- `docs/ARCHITECTURE.md` how it works
- `docs/SAFETY.md` the no-delete rule in detail
- `docs/TAKEOUT.md` Google Takeout format notes
- `docs/ROADMAP.md` what is done and what is next
- `AGENTS.md` rules for coding agents (Claude Code reads `CLAUDE.md`, Cursor reads `.cursor/rules/`, both point to it)
- `docs/tasks/` the work queue, one file per task

## Working with a coding agent
Give the agent one task: "Read `AGENTS.md`, then do `docs/tasks/04-date-sort.md`." It must pass `scripts/check.sh` (Windows: `scripts\check.ps1`) and work on `dev`.
