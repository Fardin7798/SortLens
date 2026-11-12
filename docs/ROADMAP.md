# Roadmap

## v0.1 (now): skeleton
- [x] Repo layout, settings, safety gate + undo log, health API, tests, CI

## v1
- [x] Importers: Takeout (zip parts or extracted) + folder → MediaRecord in SQLite (read-only, resumable, CLI + /api/stats)
- [x] Full Takeout metadata: archived, trashed, upload time, camera GPS, views, origin/partner sharing, Trash/Failed Videos/Untitled folders, album metadata, album copies, live-photo pairs, raw sidecar kept, `sortlens people`
- [x] Solo list from one reference photo + name (CPU face match, Takeout tags first, solo / group / check lists, database only)
- [ ] Date sort (Takeout > EXIF > filename > file time)
- [ ] Exact + near duplicates
- [ ] Live progress (SSE) + resumable batches
- [ ] Review + approve/undo flow (incl. moving an approved solo list into its folder)
- [ ] One-command setup (Windows first)

- [ ] Local UI (built last, after the backend is complete)

## Later
Blur / screenshot / meme / document categories · offline natural-language search · GPS city groups · face groups
