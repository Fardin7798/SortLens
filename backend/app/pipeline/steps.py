"""The long steps as plain functions, shared by the CLI and the job API. All are read-only on
the user's files and resumable."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.db import store
from app.importers.base import AlbumRecord
from app.importers.folder import scan_folder
from app.importers.takeout import scan_takeout

Progress = Callable[[dict[str, int]], None] | None


def import_takeout(
    con: sqlite3.Connection,
    paths: list[Path],
    *,
    batch_size: int = 50,
    on_progress: Progress = None,
) -> dict[str, int]:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"not found: {', '.join(missing)}")
    albums: list[AlbumRecord] = []
    first = paths[0].resolve()
    root = str(first.parent if first.is_file() else first)
    counts = store.import_records(
        con, scan_takeout(paths, albums), source="takeout", root=root,
        batch_size=batch_size, on_progress=on_progress,
    )  # fmt: skip
    counts["albums"] = store.save_albums(con, albums)
    return counts


def import_folder(
    con: sqlite3.Connection, path: Path, *, batch_size: int = 50, on_progress: Progress = None
) -> dict[str, int]:
    if not path.is_dir():
        raise NotADirectoryError(f"not a folder: {path}")
    return store.import_records(
        con, scan_folder(path), source="folder", root=str(path.resolve()),
        batch_size=batch_size, on_progress=on_progress,
    )  # fmt: skip


def dates(
    con: sqlite3.Connection, *, batch_size: int = 50, on_progress: Progress = None
) -> dict[str, int]:
    from app.pipeline.dates import run_dates

    return run_dates(con, batch_size=batch_size, on_progress=on_progress)


def dupes(
    con: sqlite3.Connection,
    *,
    near: bool = True,
    distance: int | None = None,
    batch_size: int = 50,
    on_progress: Progress = None,
) -> dict[str, Any]:
    from app.pipeline import dupes as d

    res = d.run(
        con, near=near, near_distance=d.NEAR_DISTANCE if distance is None else distance,
        batch_size=batch_size, on_progress=on_progress,
    )  # fmt: skip
    return {"run_id": res.run_id, **res.counts}


def solo(
    con: sqlite3.Connection,
    *,
    name: str,
    photo: Path,
    models_dir: Path,
    tagged_only: bool = False,
    threshold: float | None = None,
    batch_size: int = 50,
    on_progress: Progress = None,
) -> dict[str, Any]:
    from app.pipeline import solo as s
    from app.pipeline.faces import SAME_PERSON, OpenCVEngine

    if not photo.is_file():
        raise FileNotFoundError(f"not found: {photo}")
    engine = OpenCVEngine(models_dir)
    res = s.run(
        con, engine, name=name, ref_photo=photo.read_bytes(),
        threshold=threshold or SAME_PERSON, tagged_only=tagged_only,
        batch_size=batch_size, on_progress=on_progress,
    )  # fmt: skip
    return {"run_id": res.run_id, **res.counts}
