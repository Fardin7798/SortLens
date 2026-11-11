# Architecture

```
Takeout zips / folder ──► importer ──► MediaRecord ──► pipeline steps ──► SQLite ──► API (+SSE) ──► Next.js UI
                                                    date │ hash │ phash │ faces
```
- **MediaRecord**: path, source (takeout|folder), size, taken_at + source of date, gps, takeout fields (title, people, favorited), hashes.
- **Pipeline**: each step reads records missing its output, works in batches (default 50), commits per batch, so a stop/restart resumes.
- **Date priority**: Takeout photoTakenTime > EXIF DateTimeOriginal > date in filename > file modified time. The chosen source is stored.
- **Duplicates**: exact = SHA-256; near = perceptual hash distance; Takeout album copies and `-edited` pairs grouped.
- **Solo**: one reference photo of the user → face embedding → photos with exactly one face matching it. Takeout `people` tags as a hint.
- **Live progress**: backend streams step/batch counts over SSE; UI shows it.
