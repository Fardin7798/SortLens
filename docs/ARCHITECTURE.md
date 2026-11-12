# Architecture

```
Takeout zips / folder ──► importer ──► MediaRecord ──► pipeline steps ──► SQLite ──► API (+SSE) ──► local UI (built last)
                                                    date │ hash │ phash │ faces
```
- **MediaRecord**: path, source (takeout|folder), size, taken_at + source of date, gps, takeout fields (title, caption, people, favorite, archived, trashed, upload time, camera GPS, origin, special folder, album copy, live-photo pair, raw sidecar JSON), hashes. Albums from `metadata.json` go to the `albums` table.
- **Pipeline**: each step reads records missing its output, works in batches (default 50), commits per batch, so a stop/restart resumes.
- **Date priority**: Takeout photoTakenTime > EXIF DateTimeOriginal > date in filename > file modified time. The chosen source is stored.
- **Duplicates**: see the Duplicates section below.
- **Solo**: one reference photo of the user → face embedding → photos with exactly one face matching it. Takeout `people` tags as a hint.
- **Live progress**: backend streams step/batch counts over SSE; UI shows it.

## Faces and the solo list
- `app/pipeline/faces.py`: OpenCV YuNet (detect) + SFace (128-d embedding), CPU, photos shrunk to 1280 px. Results in `faces` (box 0..1, score, float32 embedding) and `face_scan` (one row per photo: engine, size, mtime, ok/error). A photo is scanned again only if the engine or the file changes, so runs resume.
- `app/pipeline/solo.py`: reference photo must have exactly one face. Candidates = photos tagged with the name in Takeout, plus all other photos unless `--tagged-only` (trashed, album copies, live-photo videos and failed videos are skipped). Cosine ≥ 0.363 = same person. Buckets: `solo` (one face, matches), `group` (several faces, one matches), `check` (tagged but not confirmed, with the reason). Saved in `solo_runs` / `solo_items`. No file action.
- Models live in `<data_dir>/models`, never in the repo.

## Dates
- `app/pipeline/dates.py` (`sortlens dates`): one best `taken_at` per row with `taken_at_source` = `takeout` | `takeout_live` | `exif` | `filename` | `filename_day` (WhatsApp, day only) | `file`. Takeout dates are never overwritten.
- `taken_at_offset` (minutes) only when EXIF states it; otherwise the time is stored as if UTC and means "local time, zone unknown". No zone guessing.
- File time is used only for laptop folders. For Takeout, zip/extract times are the export date, so those rows stay without a date.
- Resume marker `dates_done_at`; a re-imported (changed) file is cleared and done again. Zip parts stay open across a run (`core/media_io.MediaReader`).

## Duplicates
- `app/pipeline/dupes.py` (`sortlens dupes`): writes `dup_runs`, `dup_groups` (kind `exact` | `near` | `album_copy` | `edited`) and `dup_items` (role `keep` | `extra`). No file action.
- exact: SHA-256, computed only for files whose size matches another file. near: 64-bit pHash, BK-tree search, distance ≤ 6 bits by default (not tuned on real photos yet); each exact group counts once; every member is compared with the cluster's keep photo, so groups do not chain.
- Suggested keep: not an album copy > more pixels > real date (not file time) > bigger file > first imported.
- `edited` pairs keep both. Trash, failed videos and live-photo video halves are skipped.
- Hash cache `file_hashes` (per file, by size + mtime + hash version) makes runs resumable; one unreadable file is logged and skipped.

## Jobs and live progress
- `app/pipeline/steps.py`: the long steps (import Takeout, import folder, dates, dupes, solo) as plain functions; the CLI and the API both call them.
- `app/core/jobs.py`: one job at a time (a CPU laptop + SQLite), in a worker thread with its own connection. Progress from each batch goes to memory and to the `jobs` table about once a second. Stop is cooperative (next batch boundary); committed work stays and the step resumes when run again. A job left `running` when the app closed is marked `stopped` on next start.
- `app/api/jobs.py`: `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/stop`, `GET /api/jobs/{id}/events` (SSE: `progress` events, then one `end` with the final job; keep-alive comment every 15 s). 409 if a job is already running, 422 for bad input.

## Review and undo
- `app/core/plans.py`: `plans` + `plan_items`. A plan is built from a duplicate run (extras -> trash), a solo run (bucket -> a folder in the same location) or a list of ids. Building changes nothing. Each plan has a confirm code (hash of its items); `apply` and `undo` need it.
- Items: `move`, `mark` (file inside a Takeout zip), `skip` (with the reason: outside the location, already there, already in trash). A Takeout sidecar JSON moves with its photo unless another file still uses it.
- `apply` checks size + mtime first, moves through `core/safety.move_file`, updates `media.rel_path` / `in_trash` / `user_mark`. Restartable: done items stay done, and a move that finished just before a stop is found in the undo log.
- Importers skip `SortLens Trash`; dupes and solo skip trashed or trash-marked rows.
- API `app/api/plans.py`; apply/undo run as jobs (`apply_plan`, `undo_plan`) with live progress.
