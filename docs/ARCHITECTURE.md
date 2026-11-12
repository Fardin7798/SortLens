# Architecture

```
Takeout zips / folder ──► importer ──► MediaRecord ──► pipeline steps ──► SQLite ──► API (+SSE) ──► local UI (built last)
                                                    date │ hash │ phash │ faces
```
- **MediaRecord**: path, source (takeout|folder), size, taken_at + source of date, gps, takeout fields (title, caption, people, favorite, archived, trashed, upload time, camera GPS, origin, special folder, album copy, live-photo pair, raw sidecar JSON), hashes. Albums from `metadata.json` go to the `albums` table.
- **Pipeline**: each step reads records missing its output, works in batches (default 50), commits per batch, so a stop/restart resumes.
- **Date priority**: Takeout photoTakenTime > EXIF DateTimeOriginal > date in filename > file modified time. The chosen source is stored.
- **Duplicates**: exact = SHA-256; near = perceptual hash distance; Takeout album copies and `-edited` pairs grouped.
- **Solo**: one reference photo of the user → face embedding → photos with exactly one face matching it. Takeout `people` tags as a hint.
- **Live progress**: backend streams step/batch counts over SSE; UI shows it.

## Faces and the solo list
- `app/pipeline/faces.py`: OpenCV YuNet (detect) + SFace (128-d embedding), CPU, photos shrunk to 1280 px. Results in `faces` (box 0..1, score, float32 embedding) and `face_scan` (one row per photo: engine, size, mtime, ok/error). A photo is scanned again only if the engine or the file changes, so runs resume.
- `app/pipeline/solo.py`: reference photo must have exactly one face. Candidates = photos tagged with the name in Takeout, plus all other photos unless `--tagged-only` (trashed, album copies, live-photo videos and failed videos are skipped). Cosine ≥ 0.363 = same person. Buckets: `solo` (one face, matches), `group` (several faces, one matches), `check` (tagged but not confirmed, with the reason). Saved in `solo_runs` / `solo_items`. No file action.
- Models live in `<data_dir>/models`, never in the repo.
