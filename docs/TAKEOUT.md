# Google Takeout notes

- Export comes as several zip parts. Read all parts together.
- Folders: `Photos from YYYY` (complete) + one folder per album (second copies). Album folders have `metadata.json` (album title only).
- Sidecar per photo: `IMG.jpg.json` (old) or `IMG.jpg.supplemental-metadata.json` (since late 2024).
- Sidecar names are cut at ~51 chars, so the suffix may be truncated (`.supplemental-metad.json`, `.suppl.json`). Match: strip `.json`, then strip the last dotted part if it is a prefix of `supplemental-metadata`.
- `(1)` counter: photo `IMG(1).jpg` ↔ sidecar `IMG.jpg(1).json` or `IMG.jpg.supplemental-metadata(1).json`.
- Useful fields: `photoTakenTime.timestamp` (UTC, includes user date fixes), `creationTime`, `geoData` / `geoDataExif` (0.0, 0.0 = none), `title` (full original name), `description`, `people`, `favorited`.
- `-edited` copies share the original's sidecar. Live-photo video half usually has none. Some files have no sidecar → fall back to EXIF, filename, file time.
