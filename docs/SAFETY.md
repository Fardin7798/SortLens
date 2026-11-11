# Safety: SortLens never deletes on its own

- Scanner and importers only READ files.
- Categories are rows in the local SQLite DB, not folders on disk.
- A move or delete needs: (1) the full list shown to the user, (2) the user's explicit yes, (3) an undo log entry written BEFORE the action.
- Deletes go to a SortLens "trash" folder first, never permanent, until the user empties it.
- `undo_log.jsonl` in the data dir records every action and can reverse it.
