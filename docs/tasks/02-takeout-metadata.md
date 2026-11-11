# Task 02: Full Takeout metadata
Status: done
Roadmap line: `Full Takeout metadata`

## Why
Takeout already knows a lot (favorite, archive, trash, people, albums, origin). Saving all of it gives many categories without any AI, and the solo step can start from the `people` tags.

## Built
- `MediaRecord`: `uploaded_at`, `location_source`, `gps_lat/gps_lon`, `archived`, `trashed`, `image_views`, `origin`, `device_type`, `partner_shared`, `special_folder`, `album_copy_of`, `live_photo_of`, `sidecar_json`.
- `AlbumRecord` + `albums` table from album `metadata.json` (new and old `albumData` style, any language).
- Store: guarded `ALTER TABLE` for old databases; `importer_version` so old rows are re-read; `save_albums`, `people`, more `stats`.
- CLI: `sortlens people`; `import-takeout` also saves albums.
- Tests: `tests/test_takeout_metadata.py` (all fields, special folders, albums, album copies, live pairs, broken JSON, read-only, DB upgrade).
- Format notes in `docs/TAKEOUT.md`.

## Not in this task
EXIF/filename dates (Task 03), duplicates by hash, faces.

## Done when
- [x] All fields above stored; missing stays missing
- [x] Zips unchanged after import (test)
- [x] `scripts/check.sh` passes
