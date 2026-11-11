# Google Takeout notes

- Export comes as several zip parts. Read all parts together.
- Folders: `Photos from YYYY` (complete) + one folder per album (second copies). Album folders have `metadata.json` (album title only).
- Sidecar per photo: `IMG.jpg.json` (old) or `IMG.jpg.supplemental-metadata.json` (since late 2024).
- Sidecar names are cut at ~51 chars, so the suffix may be truncated (`.supplemental-metad.json`, `.suppl.json`). Match: strip `.json`, then strip the last dotted part if it is a prefix of `supplemental-metadata`.
- `(1)` counter: photo `IMG(1).jpg` ↔ sidecar `IMG.jpg(1).json` or `IMG.jpg.supplemental-metadata(1).json`.
- Useful fields: `photoTakenTime.timestamp` (UTC, includes user date fixes), `creationTime`, `geoData` / `geoDataExif` (0.0, 0.0 = none), `title` (full original name), `description`, `people`, `favorited`.
- `-edited` copies share the original's sidecar. Live-photo video half usually has none. Some files have no sidecar → fall back to EXIF, filename, file time.

## What SortLens keeps from each sidecar (importer v2)
| Field | Column | Notes |
|---|---|---|
| `photoTakenTime` | `taken_at`, `taken_at_source=takeout` | 0 or missing = no date |
| `creationTime` | `uploaded_at` | upload time, never used as the capture date |
| `geoData` | `lat`, `lon`, `location_source=google` | may be estimated or user-added |
| `geoDataExif` | `gps_lat`, `gps_lon` (and `lat/lon` with `camera` when `geoData` is empty) | camera GPS |
| `title`, `description`, `people`, `favorited` | same names | `sortlens people` lists names |
| `archived`, `trashed` | same names | present only when true |
| `imageViews` | `image_views` | |
| `googlePhotosOrigin` | `origin` (its key), `device_type`, `partner_shared` | e.g. `mobileUpload`, `fromPartnerSharing` |
| whole JSON | `sidecar_json` | kept as read, so later steps never need to reopen the zip for it |

## Folders
- Trash folder (`Trash`, `Bin`, `Corbeille`, `Papierkorb`, ...): `special_folder=trash`, `trashed=1`, no album.
- `Failed Videos`: `special_folder=failed_videos`, no album.
- `Untitled(n)` (and translations): still an album, `special_folder=untitled_album`. Several real albums can share one folder.
- Album `metadata.json` (any language, e.g. `métadonnées.json`): JSON with no `photoTakenTime` and a non-media name → `albums` table (title, description, access, date, location). Old style nests these under `albumData`.
- Album copy: a file in an album folder with the same name and size as one in a `Photos from YYYY` folder → `album_copy_of`.
- Live/motion photo: a video with the same stem as a photo in the same folder → `live_photo_of`; if the video has no sidecar it takes the still's date with `taken_at_source=takeout_live`.

## Re-import
Rows saved by an older importer version are re-read on the next import (`importer_version`), even when the file is unchanged.
