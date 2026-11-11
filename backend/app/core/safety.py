"""SAFETY RULE: SortLens never deletes or moves a user's file on its own.

Scanning code only reads files. Any move or delete must go through `planned_action`,
which needs an explicit user approval id and writes an undo entry first.
This module is the ONLY place allowed to touch user files.
"""

import json
from datetime import UTC, datetime
from pathlib import Path


class ApprovalRequired(RuntimeError):
    """Raised when a file action is attempted without the user's explicit yes."""


def write_undo_entry(log_path: Path, entry: dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(UTC).isoformat(), **entry}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def planned_action(*, approval_id: str | None) -> None:
    """Gate for every move/delete. v0.1 has no file actions at all."""
    if not approval_id:
        raise ApprovalRequired("User approval is required before any move or delete.")
    raise NotImplementedError("File actions come after review screen + undo are built.")
