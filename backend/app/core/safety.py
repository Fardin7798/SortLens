"""SAFETY RULES (the user's, never break):

1. SortLens never deletes a file. There is no delete code anywhere. "Delete" means: move into
   the location's own `SortLens Trash` folder. Only the user empties that folder, by hand.
2. A file is moved only for an approved plan: the user saw the full list and gave its confirm
   code (`app/core/plans.py`). No approval, no move.
3. An undo entry is written (and flushed to disk) BEFORE every move, and again after it.
4. A move never overwrites: if the target name exists, a free name ("x (1).jpg") is used.
5. Moves stay on the same drive (a rename). A move that would need copy + remove is refused.

This module is the ONLY place allowed to change user files.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class ApprovalRequired(RuntimeError):
    """A file action was attempted without the user's explicit yes."""


class CrossDrive(RuntimeError):
    """Source and target are on different drives; a plain rename is not possible."""


@dataclass(frozen=True)
class Approval:
    """Proof that the user approved one plan (its id + the confirm code they gave)."""

    plan_id: int
    code: str


def write_undo_entry(log_path: Path, entry: dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(UTC).isoformat(), **entry}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def free_name(path: Path) -> Path:
    """`path` if nothing is there, else 'name (1).ext', 'name (2).ext', ..."""
    if not path.exists():
        return path
    for n in range(1, 100000):
        p = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not p.exists():
            return p
    raise FileExistsError(f"no free name for {path}")


def _device(p: Path) -> int:
    while not p.exists():
        p = p.parent
    return p.stat().st_dev


def move_file(
    src: Path, dst: Path, *, approval: Approval | None, log_path: Path, note: dict[str, object]
) -> Path:
    """Move one file by rename after writing an undo entry. Returns where it went."""
    if approval is None or not approval.code:
        raise ApprovalRequired("User approval is required before any move.")
    if not src.is_file():
        raise FileNotFoundError(f"not found: {src}")
    if _device(src.parent) != _device(dst.parent):
        raise CrossDrive(f"{src} and {dst.parent} are on different drives")
    dst = free_name(dst)
    base = {"plan": approval.plan_id, "op": "move", "src": str(src), "dst": str(dst), **note}
    write_undo_entry(log_path, {**base, "phase": "intent"})
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():  # appeared in between: never overwrite
        raise FileExistsError(f"target appeared: {dst}")
    os.rename(src, dst)
    write_undo_entry(log_path, {**base, "phase": "done"})
    return dst
