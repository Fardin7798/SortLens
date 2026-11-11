"""Local SQLite store. Categories live here as rows; user files are never changed."""

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from app.importers.base import MediaRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    root TEXT NOT NULL,
    container TEXT NOT NULL DEFAULT '',
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    album TEXT NOT NULL DEFAULT '',
    is_edited INTEGER NOT NULL DEFAULT 0,
    sidecar TEXT NOT NULL DEFAULT '',
    taken_at REAL,
    taken_at_source TEXT NOT NULL DEFAULT '',
    lat REAL,
    lon REAL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    people TEXT NOT NULL DEFAULT '[]',
    favorited INTEGER NOT NULL DEFAULT 0,
    imported_at REAL NOT NULL,
    UNIQUE (root, container, rel_path)
);
CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    root TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    seen INTEGER NOT NULL DEFAULT 0,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
);
"""

COLS = [
    "source", "root", "container", "rel_path", "name", "kind", "size", "mtime", "album",
    "is_edited", "sidecar", "taken_at", "taken_at_source", "lat", "lon", "title",
    "description", "people", "favorited",
]  # fmt: skip


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def _row(rec: MediaRecord) -> tuple[object, ...]:
    d = asdict(rec)
    d["people"] = json.dumps(d["people"], ensure_ascii=False)
    d["is_edited"] = int(d["is_edited"])
    d["favorited"] = int(d["favorited"])
    return tuple(d[c] for c in COLS)


def import_records(
    con: sqlite3.Connection,
    records: Iterable[MediaRecord],
    *,
    source: str,
    root: str,
    batch_size: int = 50,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Upsert records in batches. Re-running skips files whose size and mtime did not change,
    so a stopped import resumes cheaply."""
    run_id = con.execute(
        "INSERT INTO import_runs (source, root, started_at) VALUES (?, ?, ?)",
        (source, root, time.time()),
    ).lastrowid
    con.commit()
    counts = {"seen": 0, "added": 0, "updated": 0, "unchanged": 0}
    placeholders = ",".join("?" * (len(COLS) + 1))
    updates = ",".join(
        f"{c}=excluded.{c}" for c in COLS if c not in ("root", "container", "rel_path")
    )
    try:
        for i, rec in enumerate(records, 1):
            counts["seen"] += 1
            old = con.execute(
                "SELECT size, mtime FROM media WHERE root=? AND container=? AND rel_path=?",
                (rec.root, rec.container, rec.rel_path),
            ).fetchone()
            if old and old[0] == rec.size and abs(old[1] - rec.mtime) < 1e-6:
                counts["unchanged"] += 1
            else:
                con.execute(
                    f"INSERT INTO media ({','.join(COLS)}, imported_at) VALUES ({placeholders}) "
                    f"ON CONFLICT(root, container, rel_path) DO UPDATE SET {updates}, "
                    "imported_at=excluded.imported_at",
                    (*_row(rec), time.time()),
                )
                counts["updated" if old else "added"] += 1
            if i % batch_size == 0:
                _save_run(con, run_id, counts, "running")
                if on_progress:
                    on_progress(dict(counts))
        _save_run(con, run_id, counts, "done")
    except BaseException:
        _save_run(con, run_id, counts, "stopped")
        raise
    if on_progress:
        on_progress(dict(counts))
    return counts


def _save_run(con: sqlite3.Connection, run_id: int | None, c: dict[str, int], status: str) -> None:
    con.execute(
        "UPDATE import_runs SET seen=?, added=?, updated=?, unchanged=?, status=?, finished_at=? "
        "WHERE id=?",
        (c["seen"], c["added"], c["updated"], c["unchanged"], status,
         None if status == "running" else time.time(), run_id),
    )  # fmt: skip
    con.commit()


def stats(con: sqlite3.Connection) -> dict[str, int]:
    q = lambda sql: int(con.execute(sql).fetchone()[0])  # noqa: E731
    return {
        "total": q("SELECT COUNT(*) FROM media"),
        "photos": q("SELECT COUNT(*) FROM media WHERE kind='photo'"),
        "videos": q("SELECT COUNT(*) FROM media WHERE kind='video'"),
        "takeout": q("SELECT COUNT(*) FROM media WHERE source='takeout'"),
        "folder": q("SELECT COUNT(*) FROM media WHERE source='folder'"),
        "with_date": q("SELECT COUNT(*) FROM media WHERE taken_at IS NOT NULL"),
        "without_date": q("SELECT COUNT(*) FROM media WHERE taken_at IS NULL"),
        "with_location": q("SELECT COUNT(*) FROM media WHERE lat IS NOT NULL"),
        "takeout_without_sidecar": q(
            "SELECT COUNT(*) FROM media WHERE source='takeout' AND sidecar=''"
        ),
    }
