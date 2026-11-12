# Safety: SortLens never deletes

The user's rules. Code and tests enforce them.

1. **No delete, anywhere.** There is no delete code in `backend/app` (a test scans the code for it). "Delete" means: move into that location's own `SortLens Trash` folder, keeping the same sub-folders. Only the user empties it, by hand.
2. **Scans only read.** Import, dates, duplicates and solo only read files. Their results are rows in the local SQLite database.
3. **Full list first, then yes.** A file moves only through a plan (`app/core/plans.py`): the plan is built (nothing moves), the user sees every item, and applies it with the plan's confirm code. A wrong code moves nothing.
4. **Undo log before every move.** `undo_log.jsonl` in the data folder gets an entry (flushed to disk) before and after each move. `undo` moves everything back. If the app stops mid-plan, the log is used to finish cleanly.
5. **Never overwrite.** If the target name exists, a free name like `a (1).jpg` is used.
6. **Same drive only.** A move is a rename. Anything that would need copy + remove is refused.
7. **Changed since scan = not moved.** If a file's size or time changed after the scan, it is skipped.
8. **Takeout zips are never changed.** Files inside a zip only get a mark in the database.
9. **One place touches files:** `app/core/safety.py` (`move_file`). Nothing else may rename or remove a user file.
