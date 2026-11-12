# Task 06: Live progress (jobs + SSE)
Status: done
Roadmap line: `Live progress (SSE) + resumable batches`

## Why
The UI (built last) must start long steps and show live progress, and the user must be able to stop safely and continue later.

## Built
- `app/pipeline/steps.py`: shared step functions (CLI import now uses them too).
- `app/core/jobs.py`: `JobManager` (one job at a time, worker thread, `jobs` table, cooperative stop, crash marker) and `manager()`.
- `app/api/jobs.py`: start, list, get, stop, SSE events. Wired in `app/main.py`.
- Tests: `tests/test_jobs.py` (import + dates through the API with SSE, stop mid-run, 409 busy, 422 bad input, 404, failed job, app-closed marker, dupes job).

## Rules
- Jobs only run the read-only steps. No job can move or delete files.
- API listens on 127.0.0.1 only (settings.host).

## Out of scope
Review + undo (next), auth (local only), several jobs in parallel.

## Done when
- [x] Every long step can run as a job with live progress
- [x] Stop keeps finished work; running again resumes
- [x] `scripts/check.sh` passes
