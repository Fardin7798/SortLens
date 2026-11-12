# Task 05: Duplicates
Status: done
Roadmap line: `Exact + near duplicates`

## Why
Show which photos and videos are copies, so the user can later free space in review. Lists only.

## Built
- `app/pipeline/dupes.py`: `run(con, *, near=True, near_distance=6, batch_size=50, on_progress=None)` and `groups(con, run_id, kind=None)`.
- Tables: `file_hashes` (cache), `dup_runs`, `dup_groups`, `dup_items`.
- `app/core/media_io.MediaReader.open()` streams big files (videos) from a zip or folder.
- CLI: `sortlens dupes [--no-near] [--distance N]`, `sortlens dupes-show RUN [--kind K]`.
- Tests: `tests/test_dupes.py` (exact photo + video, near resize/re-save, album copy, edited pair, trash skipped, broken file, size-only hashing, cache resume, near off, BK-tree).

## Rules
- No copy, move or delete. Only rows. Keep is a suggestion; the user decides in review.
- Takeout trash, failed videos and live-photo video halves are skipped.
- One unreadable file does not stop the run.

## Out of scope
Acting on the lists (review + undo task), video near-duplicates, tuning the near distance on real photos (after the real Takeout test).

## Done when
- [x] Four kinds of groups built with a suggested keep
- [x] Resumable through the hash cache
- [x] `scripts/check.sh` passes
