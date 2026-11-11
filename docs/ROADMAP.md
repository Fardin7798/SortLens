# Roadmap

## v0.1 (now): skeleton
- [x] Repo layout, settings, safety gate + undo log, health API, tests, CI

## v1
- [x] Importers: Takeout (zip parts or extracted) + folder → MediaRecord in SQLite (read-only, resumable, CLI + /api/stats)
- [x] Full Takeout metadata: archived, trashed, upload time, camera GPS, views, origin/partner sharing, Trash/Failed Videos/Untitled folders, album metadata, album copies, live-photo pairs, raw sidecar kept, `sortlens people`
- [ ] Date sort (Takeout > EXIF > filename > file time)
- [ ] Exact + near duplicates
- [ ] Solo category from one reference photo (CPU)
- [ ] Live progress (SSE) + resumable batches
- [ ] Review screen + approve/undo flow
- [ ] One-command setup (Windows first)

- [ ] Local UI (built last, after the backend is complete)

## Later
Blur / screenshot / meme / document categories · offline natural-language search · GPS city groups · face groups
