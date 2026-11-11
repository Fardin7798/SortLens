# Task 03: Date sort
Status: todo
Roadmap line: `Date sort (Takeout > EXIF > filename > file time)`

## Why
Every photo and video needs one best "taken at" date, with the source recorded, so the UI can group by year/month and show honestly where each date came from.

## Read first
- `AGENTS.md`
- `docs/TAKEOUT.md` (Takeout `photoTakenTime` is already stored by the importer)
- `backend/app/importers/base.py` (`MediaRecord`), `backend/app/db/store.py` (schema)

## Build
1. `backend/app/pipeline/dates.py` with one public function:
   `run_dates(con, *, open_file, batch_size=50, on_progress=None) -> dict[str, int]`
   - `open_file(row) -> BinaryIO` opens a media file **read-only**, whether plain (`root/rel_path`) or inside a zip (`container` + `rel_path`, via `zipfile`). Put this opener in `backend/app/importers/` so later steps reuse it.
2. Priority for each row (stop at the first that gives a date):
   1. `takeout` / `takeout_live` — already set by the importer. **Never overwrite it.**
   2. `exif` — photos only: EXIF `DateTimeOriginal`, else `DateTimeDigitized` (Pillow; `pillow-heif` for HEIC). Use `OffsetTimeOriginal` when present.
   3. `filename` — patterns: `IMG_20230514_123456`, `PXL_20230514_123456789`, `VID_20230514_123456`, `Screenshot_2023-05-14-12-34-56`, `IMG-20230514-WA0001` (WhatsApp, date only), `2023-05-14 12.34.56`, `20230514_123456`. Reject impossible dates (year < 1990 or in the future).
   4. `file` — file mtime (plain file) or zip entry time. Lowest trust.
3. Schema (add with guarded `ALTER TABLE` in `store.connect()`):
   - `taken_at_offset INTEGER` — minutes from UTC, NULL when unknown.
   - `dates_done_at REAL` — when this step finished the row (resume marker).
   EXIF/filename times without an offset are stored as if UTC with `taken_at_offset = NULL`; the UI later shows them as "local time, zone unknown". Do not guess a zone.
4. Resume: only rows with `dates_done_at IS NULL` are processed; commit every batch. Re-running after a stop continues; re-running after finish does nothing. A re-imported (changed) file must get `dates_done_at = NULL` again (set it in `import_records` on update).
5. CLI: `sortlens dates` runs the step and prints counts per source. `sortlens stats` adds `date_takeout`, `date_exif`, `date_filename`, `date_file`, `date_missing`.
6. Tests in `backend/tests/test_dates.py`, data generated in `tmp_path`:
   - JPEG with EXIF DateTimeOriginal (+ one with OffsetTimeOriginal), JPEG without EXIF but dated filename, file with neither (→ `file`), Takeout row keeps `takeout`, same cases inside a zip, broken/truncated JPEG does not crash (falls through), resume after a stop, files' bytes and mtimes unchanged after the run.

## Rules for this task
- Read-only. Open files with `"rb"` / `zipfile` read; never write next to user files.
- One unreadable file must not stop the run: log it, fall through to the next source.
- Videos: no EXIF parsing in this task (no ffprobe); use filename, then file time.
- No new dependency (Pillow and pillow-heif are already there).

## Out of scope
Duplicates, faces, API/SSE, frontend, video metadata (creation_time), timezone guessing from GPS.

## Done when
- [ ] Every media row has `dates_done_at` set and, where any source gives one, `taken_at` + `taken_at_source`
- [ ] Takeout dates untouched; offsets stored only when the file states them
- [ ] All tests above pass; `scripts/check.sh` passes
- [ ] `docs/ROADMAP.md` ticked, this file `Status: done`, `docs/tasks/README.md` table updated
