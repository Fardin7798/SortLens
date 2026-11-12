# Task 08: Windows one-command setup
Status: review (done when the `windows-setup` CI job is green)
Roadmap line: `One-command setup (Windows first)`

## Why
The user runs SortLens on an HP 15s (i3 12th gen, Windows 11, no GPU). One command must make it ready, with no Python knowledge needed.

## Built
- `scripts/setup.ps1`: installs uv if missing, Python 3.12, pinned packages from `backend/uv.lock` (`uv sync --locked`), face models, then `sortlens doctor`. Options `-DataDir`, `-NoFaces`, `-Dev`. Re-runnable. Never touches photos.
- `sortlens.cmd` (repo root): runs SortLens from the folder without activating anything.
- `backend/uv.lock`: exact versions, same on every machine.
- `sortlens doctor` (`app/core/doctor.py`): Python, SQLite, data folder writable, free space, packages, faces + models. Exit 1 when a required check fails.
- `.gitattributes`: CRLF for `.cmd`/`.ps1`.
- CI job `windows-setup` (windows-latest): runs setup with a data folder path that has a space, the launcher, then every check on Windows.

## Out of scope
An installer (.exe/.msi), auto-update, the UI.

## Done when
- [x] `setup.ps1` parses (PowerShell 7 parser), `doctor` tests pass on Linux
- [ ] `windows-setup` CI job green (setup + launcher + all tests on real Windows)
