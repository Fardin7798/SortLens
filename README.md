# SortLens

Local-first, offline photo organizer. Point it at a **Google Takeout** export or any **laptop folder**, and it sorts your photos by date, finds duplicates, and collects photos where you are alone, while a local web page shows live progress.

> **Safety promise:** SortLens never deletes or moves your photos on its own. It only categorizes. Any move or delete happens only after it shows you the full list and you say yes, and every action can be undone.

## Status
Early development (v0.1 skeleton). See `docs/ROADMAP.md`.

## Runs on
Windows / Linux / macOS, CPU only (built and tested for a 12th-gen i3 laptop, no GPU), fully offline.

## Quick start (dev)
```bash
# backend
cd backend
uv venv && uv pip install -e ".[dev]"
uv run sortlens serve        # http://127.0.0.1:8765/api/health

# frontend
cd frontend
npm install
npm run dev                   # http://localhost:3000
```
Import photos (read-only, safe to re-run; it resumes):
```bash
uv run sortlens import-takeout takeout-001.zip takeout-002.zip   # or an extracted Takeout folder
uv run sortlens import-folder "D:/Photos"
uv run sortlens stats
```
A one-command setup script comes in v1.

## Docs
- `docs/ARCHITECTURE.md` how it works
- `docs/SAFETY.md` the no-delete rule in detail
- `docs/TAKEOUT.md` Google Takeout format notes
- `docs/ROADMAP.md` what is done and what is next
- `AGENTS.md` rules for coding agents working on this repo
