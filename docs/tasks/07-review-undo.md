# Task 07: Review + undo
Status: done
Roadmap line: `Review + approve/undo`

## Why
After the lists, the user decides. Files move only for a list he saw in full and approved, and every move can be undone. User's rule (2026-11-12): no delete at all; "delete" = move into the location's `SortLens Trash`.

## Built
- `app/core/safety.py`: `Approval`, `move_file` (approval required, undo entry before and after, never overwrite, same drive only), `free_name`. `planned_action` removed.
- `app/core/plans.py`: create / from_dupes / from_solo / get / recent / check / apply / undo.
- Media columns `in_trash`, `user_mark`; stats `in_sortlens_trash`, `marked_in_zip`. `TRASH_DIR` skipped by importers, dupes and solo.
- Jobs `apply_plan`, `undo_plan`; API `app/api/plans.py`; CLI `plan-trash-dupes`, `plan-move-solo`, `plan-show`, `apply`, `undo`.
- Tests: `tests/test_plans.py`, `tests/test_safety.py` (incl. a code scan: no delete calls in app/), API test in `tests/test_jobs.py`.

## Out of scope
Emptying the trash (the user does it by hand), moves across drives, UI.

## Done when
- [x] No file moves without the plan's code; wrong code moves nothing
- [x] Trash, move, zip mark, sidecar, never overwrite, changed file skipped, undo, stop/resume
- [x] `scripts/check.sh` passes
