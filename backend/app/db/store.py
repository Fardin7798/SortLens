"""Local SQLite store. Categories live here as rows; user files are never changed."""

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from app.importers.base import AlbumRecord, MediaRecord

# Bump when importers start reading new facts: rows saved by an older version are re-read
# on the next import even if the file itself did not change.
IMPORTER_VERSION = 2

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
CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    folder TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    access TEXT NOT NULL DEFAULT '',
    date REAL,
    lat REAL,
    lon REAL,
    UNIQUE (root, folder)
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
    "location_source", "gps_lat", "gps_lon", "uploaded_at", "archived", "trashed",
    "image_views", "origin", "device_type", "partner_shared", "special_folder",
    "album_copy_of", "live_photo_of", "sidecar_json", "importer_version",
]  # fmt: skip
BOOL_COLS = {"is_edited", "favorited", "archived", "trashed", "partner_shared"}

# Columns added after v0.1. connect() adds any that an older database lacks.
ADDED_COLUMNS = {
    "location_source": "TEXT NOT NULL DEFAULT ''",
    "gps_lat": "REAL",
    "gps_lon": "REAL",
    "uploaded_at": "REAL",
    "archived": "INTEGER NOT NULL DEFAULT 0",
    "trashed": "INTEGER NOT NULL DEFAULT 0",
    "image_views": "INTEGER",
    "origin": "TEXT NOT NULL DEFAULT ''",
    "device_type": "TEXT NOT NULL DEFAULT ''",
    "partner_shared": "INTEGER NOT NULL DEFAULT 0",
    "special_folder": "TEXT NOT NULL DEFAULT ''",
    "album_copy_of": "TEXT NOT NULL DEFAULT ''",
    "live_photo_of": "TEXT NOT NULL DEFAULT ''",
    "sidecar_json": "TEXT NOT NULL DEFAULT ''",
    "importer_version": "INTEGER NOT NULL DEFAULT 1",
    "taken_at_offset": "INTEGER",  # minutes from UTC, only when the file states it
    "dates_done_at": "REAL",
    "in_trash": "INTEGER NOT NULL DEFAULT 0",  # moved into its location's "SortLens Trash"
    "user_mark": "TEXT NOT NULL DEFAULT ''",  # zip files can't move: 'trash' / 'move' mark only  # set by pipeline/dates.py; NULL = still to do
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(media)")}
    for col, decl in ADDED_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE media ADD COLUMN {col} {decl}")
    con.commit()
    return con


def _row(rec: MediaRecord) -> tuple[object, ...]:
    d = asdict(rec)
    d["people"] = json.dumps(d["people"], ensure_ascii=False)
    for c in BOOL_COLS:
        d[c] = int(d[c])
    d["importer_version"] = IMPORTER_VERSION
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
                "SELECT size, mtime, importer_version FROM media "
                "WHERE root=? AND container=? AND rel_path=?",
                (rec.root, rec.container, rec.rel_path),
            ).fetchone()
            if (
                old
                and old[0] == rec.size
                and abs(old[1] - rec.mtime) < 1e-6
                and old[2] >= IMPORTER_VERSION
            ):
                counts["unchanged"] += 1
            else:
                con.execute(
                    f"INSERT INTO media ({','.join(COLS)}, imported_at) VALUES ({placeholders}) "
                    f"ON CONFLICT(root, container, rel_path) DO UPDATE SET {updates}, "
                    "imported_at=excluded.imported_at, taken_at_offset=NULL, dates_done_at=NULL",
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


def save_albums(con: sqlite3.Connection, albums: Iterable[AlbumRecord]) -> int:
    n = 0
    for a in albums:
        con.execute(
            "INSERT INTO albums (root, folder, title, description, access, date, lat, lon) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(root, folder) DO UPDATE SET "
            "title=excluded.title, description=excluded.description, access=excluded.access, "
            "date=excluded.date, lat=excluded.lat, lon=excluded.lon",
            (a.root, a.folder, a.title, a.description, a.access, a.date, a.lat, a.lon),
        )
        n += 1
    con.commit()
    return n


def people(con: sqlite3.Connection) -> list[tuple[str, int]]:
    """Names tagged in Google Photos with how many files carry each, most first."""
    rows = con.execute(
        "SELECT j.value, COUNT(*) FROM media, json_each(media.people) AS j "
        "GROUP BY j.value ORDER BY COUNT(*) DESC, j.value"
    ).fetchall()
    return [(str(r[0]), int(r[1])) for r in rows]


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
        "date_takeout": q(
            "SELECT COUNT(*) FROM media WHERE taken_at_source IN ('takeout','takeout_live')"
        ),
        "date_exif": q("SELECT COUNT(*) FROM media WHERE taken_at_source='exif'"),
        "date_filename": q("SELECT COUNT(*) FROM media WHERE taken_at_source LIKE 'filename%'"),
        "date_file": q("SELECT COUNT(*) FROM media WHERE taken_at_source='file'"),
        "date_missing": q("SELECT COUNT(*) FROM media WHERE taken_at IS NULL"),
        "dates_todo": q("SELECT COUNT(*) FROM media WHERE dates_done_at IS NULL"),
        "with_location": q("SELECT COUNT(*) FROM media WHERE lat IS NOT NULL"),
        "takeout_without_sidecar": q(
            "SELECT COUNT(*) FROM media WHERE source='takeout' AND sidecar=''"
        ),
        "location_google": q("SELECT COUNT(*) FROM media WHERE location_source='google'"),
        "location_camera": q("SELECT COUNT(*) FROM media WHERE location_source='camera'"),
        "favorites": q("SELECT COUNT(*) FROM media WHERE favorited=1"),
        "archived": q("SELECT COUNT(*) FROM media WHERE archived=1"),
        "trashed": q("SELECT COUNT(*) FROM media WHERE trashed=1"),
        "partner_shared": q("SELECT COUNT(*) FROM media WHERE partner_shared=1"),
        "failed_videos": q("SELECT COUNT(*) FROM media WHERE special_folder='failed_videos'"),
        "in_albums": q("SELECT COUNT(*) FROM media WHERE album!=''"),
        "album_copies": q("SELECT COUNT(*) FROM media WHERE album_copy_of!=''"),
        "edited": q("SELECT COUNT(*) FROM media WHERE is_edited=1"),
        "live_videos": q("SELECT COUNT(*) FROM media WHERE live_photo_of!=''"),
        "with_people": q("SELECT COUNT(*) FROM media WHERE people!='[]'"),
        "people_names": q(
            "SELECT COUNT(DISTINCT j.value) FROM media, json_each(media.people) AS j"
        ),
        "albums": q("SELECT COUNT(*) FROM albums"),
        "in_sortlens_trash": q("SELECT COUNT(*) FROM media WHERE in_trash=1"),
        "marked_in_zip": q("SELECT COUNT(*) FROM media WHERE user_mark!=''"),
    }
