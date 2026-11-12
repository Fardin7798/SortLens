# Task 03: Solo list
Status: done
Roadmap line: `Solo list from one reference photo + name`

## Why
The user gives one photo and a name and gets the photos where that person is alone, ready to review. Moving them into a folder comes later, in the review + undo task, only after the user says yes.

## Built
- `app/core/media_io.py`: read a file's bytes from a zip part or a folder (read-only).
- `app/pipeline/faces.py`: `FaceEngine` protocol, `OpenCVEngine` (YuNet + SFace, CPU), model download with SHA-256 check, resumable `scan()` with `faces` + `face_scan` tables.
- `app/pipeline/solo.py`: `run()` builds solo / group / check lists into `solo_runs` + `solo_items`; `items()` reads them.
- CLI: `sortlens models download`, `sortlens solo NAME --photo REF [--tagged-only] [--threshold]`, `sortlens solo-show RUN [--bucket]`.
- Optional extra `faces` (opencv-python-headless, numpy). Core install and CI do not need it.
- Tests: `tests/test_solo.py` with a fake engine (buckets, reasons, tagged-only, resume, engine change, bad reference, zip untouched).

## Rules
- Reference photo with 0 or 2+ faces is refused.
- Unreadable photo: recorded as error; a tagged one goes to `check`, nothing is guessed.
- No copy, move or delete.

## Out of scope
Moving the approved list (review + undo task), face groups for unknown people, speed tuning on the real laptop.

## Done when
- [x] Lists built from Takeout tags + face match, untagged photos searched too
- [x] Resumes without rescanning
- [x] `scripts/check.sh` passes
