"""Solo category: photos where one chosen person is alone.

Flow (user's design): one reference photo + a name -> photos tagged with that name in
Takeout are the first candidates -> a CPU face match checks them, and also searches untagged
photos -> photos with exactly ONE face that matches = "<name> akela"; photos where the person
is one of several faces = group list; tagged photos the match could not confirm = check list.

Only database rows are written. No file is copied, moved or deleted here.
"""

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.pipeline import faces as F

SCHEMA = """
CREATE TABLE IF NOT EXISTS solo_runs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ref_sha256 TEXT NOT NULL,
    engine TEXT NOT NULL,
    threshold REAL NOT NULL,
    tagged_only INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS solo_items (
    run_id INTEGER NOT NULL,
    media_id INTEGER NOT NULL,
    bucket TEXT NOT NULL,          -- solo | group | check
    reason TEXT NOT NULL DEFAULT '',
    similarity REAL,
    n_faces INTEGER NOT NULL,
    tagged INTEGER NOT NULL,
    PRIMARY KEY (run_id, media_id)
);
"""

BASE = (
    "kind='photo' AND trashed=0 AND in_trash=0 AND user_mark!='trash' AND album_copy_of='' AND live_photo_of='' "
    "AND special_folder!='failed_videos'"
)
TAGGED = "EXISTS (SELECT 1 FROM json_each(media.people) j WHERE lower(j.value)=lower(?))"


class ReferenceError_(ValueError):
    """The reference photo cannot be used (no face, or more than one)."""


@dataclass
class SoloResult:
    run_id: int
    counts: dict[str, int] = field(default_factory=dict)


def reference_embedding(engine: F.FaceEngine, data: bytes) -> list[float]:
    found = engine.faces(data)
    if len(found) != 1:
        raise ReferenceError_(f"reference photo must show exactly one face; found {len(found)}")
    return found[0].embedding


def run(
    con: sqlite3.Connection,
    engine: F.FaceEngine,
    *,
    name: str,
    ref_photo: bytes,
    threshold: float = F.SAME_PERSON,
    tagged_only: bool = False,
    batch_size: int = 50,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> SoloResult:
    name = name.strip()
    if not name:
        raise ValueError("name is empty")
    ref = reference_embedding(engine, ref_photo)
    con.executescript(SCHEMA)
    tagged = [r[0] for r in con.execute(f"SELECT id FROM media WHERE {BASE} AND {TAGGED}", (name,))]
    others: list[int] = []
    if not tagged_only:
        others = [
            r[0]
            for r in con.execute(f"SELECT id FROM media WHERE {BASE} AND NOT {TAGGED}", (name,))
        ]
    scan = F.scan(con, engine, tagged + others, batch_size=batch_size, on_progress=on_progress)

    cur = con.execute(
        "INSERT INTO solo_runs (name, ref_sha256, engine, threshold, tagged_only, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (name, hashlib.sha256(ref_photo).hexdigest(), engine.version, threshold,
         int(tagged_only), time.time()),
    )  # fmt: skip
    run_id = int(cur.lastrowid or 0)
    counts = {"tagged": len(tagged), "searched_untagged": len(others), "solo": 0, "group": 0,
              "check": 0, "scan_errors": scan["errors"]}  # fmt: skip
    tagged_set = set(tagged)
    for mid in tagged + others:
        st = F.scan_status(con, mid)
        embs = F.faces_of(con, mid)
        best = max((F.similarity(ref, e) for e in embs), default=None)
        is_tagged = mid in tagged_set
        if st is None or st[0] != "ok":
            bucket, reason = ("check", "photo could not be read") if is_tagged else ("", "")
        elif best is not None and best >= threshold:
            bucket, reason = ("solo", "") if len(embs) == 1 else ("group", "")
        elif is_tagged:
            bucket = "check"
            reason = "no face found" if not embs else "tagged, face did not match"
        else:
            bucket, reason = "", ""
        if bucket:
            con.execute(
                "INSERT INTO solo_items VALUES (?,?,?,?,?,?,?)",
                (run_id, mid, bucket, reason, best, len(embs), int(is_tagged)),
            )
            counts[bucket] += 1
    con.commit()
    return SoloResult(run_id, counts)


def items(con: sqlite3.Connection, run_id: int, bucket: str | None = None) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    q = (
        "SELECT s.bucket, s.reason, s.similarity, s.n_faces, s.tagged, m.id, m.name, m.rel_path, "
        "m.container, m.root, m.taken_at FROM solo_items s JOIN media m ON m.id=s.media_id "
        "WHERE s.run_id=?"
    )
    args: list[object] = [run_id]
    if bucket:
        q += " AND s.bucket=?"
        args.append(bucket)
    rows = con.execute(q + " ORDER BY s.bucket, m.taken_at, m.rel_path", args).fetchall()
    con.row_factory = None
    return rows
