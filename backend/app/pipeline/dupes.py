"""Duplicate lists. Nothing is deleted or moved: this only writes groups to the database.

Kinds of group:
  exact       same bytes (SHA-256). Only files whose size matches another file are hashed.
  near        photos that look the same (64-bit perceptual hash, Hamming distance <= threshold):
              resized, re-saved, WhatsApp copies, burst shots. Each exact group counts once.
  album_copy  Takeout album folder copy of a photo in "Photos from YYYY" (found by the importer).
  edited      Google Photos "-edited" file next to its original. Both are worth keeping.

Each group has a suggested `keep` file and `extra` files; the user decides later in review.
Skipped everywhere: Takeout trash, failed videos, live-photo video halves.
Resumable: hashes are cached per file and reused while size and mtime are unchanged.
"""

import hashlib
import io
import json
import logging
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from posixpath import dirname
from typing import Any

from PIL import Image

from app.core.media_io import MediaReader
from app.importers.takeout import _media_key

log = logging.getLogger(__name__)

HASH_VERSION = "sha256+phash64-v1"
NEAR_DISTANCE = 6  # of 64 bits; common choice for pHash, not tuned on the user's photos yet
CHUNK = 1 << 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_hashes (
    media_id INTEGER PRIMARY KEY,
    version TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL DEFAULT '',
    phash TEXT NOT NULL DEFAULT '',
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL,          -- ok | error
    error TEXT NOT NULL DEFAULT '',
    done_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dup_runs (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL,
    near_distance INTEGER NOT NULL,
    counts TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS dup_groups (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    kind TEXT NOT NULL             -- exact | near | album_copy | edited
);
CREATE TABLE IF NOT EXISTS dup_items (
    group_id INTEGER NOT NULL,
    media_id INTEGER NOT NULL,
    role TEXT NOT NULL,            -- keep | extra
    distance INTEGER,              -- near only: bits from the keep photo
    PRIMARY KEY (group_id, media_id)
);
"""

SKIP = (
    "trashed=0 AND in_trash=0 AND user_mark!='trash' AND special_folder!='failed_videos' "
    "AND live_photo_of=''"
)


@dataclass
class Row:
    id: int
    source: str
    root: str
    container: str
    rel_path: str
    name: str
    kind: str
    size: int
    mtime: float
    album_copy_of: str
    is_edited: int
    taken_at_source: str


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _rows(con: sqlite3.Connection, where: str = "") -> list[Row]:
    q = (
        "SELECT id, source, root, container, rel_path, name, kind, size, mtime, album_copy_of, "
        f"is_edited, taken_at_source FROM media WHERE {SKIP} {where} ORDER BY id"
    )
    return [Row(*r) for r in con.execute(q)]


# ---------- hashing ----------


def _phash(data: bytes) -> tuple[str, int, int]:
    """64-bit DCT perceptual hash (same idea as imagehash.phash), plus size in pixels."""
    import imagehash

    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        im.draft("L", (256, 256))  # fast JPEG decode at reduced size
        return str(imagehash.phash(im)), w, h


def _sha256(rd: MediaReader, r: Row) -> str:
    h = hashlib.sha256()
    with rd.open(r.root, r.container, r.rel_path) as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def hash_files(
    con: sqlite3.Connection,
    rows: list[Row],
    need_sha: set[int],
    rd: MediaReader,
    *,
    batch_size: int = 50,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Fill file_hashes for `rows`: sha256 for ids in need_sha, phash for photos. Resumable."""
    _heif()
    old = {
        r[0]: r[1:]
        for r in con.execute("SELECT media_id, version, size, mtime, sha256 FROM file_hashes")
    }
    c = {"todo": len(rows), "hashed": 0, "cached": 0, "errors": 0}
    for i, r in enumerate(rows, 1):
        o = old.get(r.id)
        fresh = o and o[0] == HASH_VERSION and o[1] == r.size and abs(o[2] - r.mtime) < 1e-6
        if fresh and (r.id not in need_sha or o[3]):  # type: ignore[index]
            c["cached"] += 1
        else:
            sha, ph, w, h, err = "", "", None, None, ""
            try:
                if r.id in need_sha:
                    sha = _sha256(rd, r)
                if r.kind == "photo":
                    try:
                        ph, w, h = _phash(rd.read(r.root, r.container, r.rel_path))
                    except Exception as e:  # undecodable photo: exact match still works
                        err = f"image: {type(e).__name__}: {e}"[:300]
            except Exception as e:  # unreadable file
                err = f"{type(e).__name__}: {e}"[:300]
                log.warning("could not read %s: %s", r.rel_path, e)
            status = "error" if err and not (sha or ph) else "ok"
            c["errors"] += status == "error"
            con.execute(
                "INSERT OR REPLACE INTO file_hashes (media_id, version, size, mtime, sha256, "
                "phash, width, height, status, error, done_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r.id, HASH_VERSION, r.size, r.mtime, sha, ph, w, h, status, err, time.time()),
            )
            c["hashed"] += 1
        if i % batch_size == 0:
            con.commit()
            if on_progress:
                on_progress(dict(c))
    con.commit()
    return c


_heif_ready = False


def _heif() -> None:
    global _heif_ready
    if not _heif_ready:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:  # pragma: no cover
            pass
        _heif_ready = True


# ---------- grouping ----------


class _BKTree:
    """Hamming-distance BK-tree: finds hashes within d bits without comparing all pairs."""

    def __init__(self) -> None:
        self.root: list[Any] | None = None  # [value, id, {dist: child}]

    def add(self, v: int, ident: int) -> None:
        if self.root is None:
            self.root = [v, ident, {}]
            return
        node = self.root
        while True:
            d = (v ^ node[0]).bit_count()
            nxt = node[2].get(d)
            if nxt is None:
                node[2][d] = [v, ident, {}]
                return
            node = nxt

    def near(self, v: int, maxd: int) -> Iterable[tuple[int, int]]:
        stack = [self.root] if self.root else []
        while stack:
            node = stack.pop()
            d = (v ^ node[0]).bit_count()
            if d <= maxd:
                yield node[1], d
            for k, child in node[2].items():
                if d - maxd <= k <= d + maxd:
                    stack.append(child)


def _keep_order(r: Row, px: int) -> tuple[int, ...]:
    """Lower is better: from 'Photos from YYYY' not an album copy, bigger picture, real date,
    bigger file, older id."""
    return (
        int(bool(r.album_copy_of)),
        -px,
        int(r.taken_at_source in ("", "file")),
        -r.size,
        r.id,
    )


@dataclass
class DupResult:
    run_id: int
    counts: dict[str, int]


def run(
    con: sqlite3.Connection,
    *,
    near_distance: int = NEAR_DISTANCE,
    near: bool = True,
    batch_size: int = 50,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> DupResult:
    """Hash what is needed and write a fresh set of duplicate groups. No file is changed."""
    ensure_schema(con)
    rows = [r for r in _rows(con) if not r.album_copy_of]  # album copies: own group kind
    by_size: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        if r.size > 0:
            by_size[r.size].append(r)
    need_sha = {r.id for g in by_size.values() if len(g) > 1 for r in g}
    to_hash = [r for r in rows if r.id in need_sha or (near and r.kind == "photo")]
    with MediaReader() as rd:
        hc = hash_files(con, to_hash, need_sha, rd, batch_size=batch_size, on_progress=on_progress)

    info = {
        m: (sha, ph, (w or 0) * (h or 0))
        for m, sha, ph, w, h in con.execute(
            "SELECT media_id, sha256, phash, width, height FROM file_hashes WHERE version=?",
            (HASH_VERSION,),
        )
    }
    byid = {r.id: r for r in rows}
    px = lambda i: info.get(i, ("", "", 0))[2]  # noqa: E731
    order = lambda i: _keep_order(byid[i], px(i))  # noqa: E731

    run_id = con.execute(
        "INSERT INTO dup_runs (started_at, near_distance) VALUES (?, ?)",
        (time.time(), near_distance),
    ).lastrowid
    assert run_id is not None
    counts = {"exact": 0, "near": 0, "album_copy": 0, "edited": 0, "extra_files": 0,
              "extra_bytes": 0, **{f"hash_{k}": v for k, v in hc.items()}}  # fmt: skip

    def group(kind: str, keep: int, others: list[tuple[int, int | None]], extra: bool) -> None:
        gid = con.execute(
            "INSERT INTO dup_groups (run_id, kind) VALUES (?, ?)", (run_id, kind)
        ).lastrowid
        con.execute("INSERT INTO dup_items VALUES (?, ?, 'keep', NULL)", (gid, keep))
        for m, d in others:
            con.execute(
                "INSERT INTO dup_items VALUES (?, ?, ?, ?)",
                (gid, m, "extra" if extra else "keep", d),
            )
        counts[kind] += 1
        if extra:
            counts["extra_files"] += len(others)

    # exact
    by_sha: dict[str, list[int]] = defaultdict(list)
    for i in need_sha:
        sha = info.get(i, ("",))[0]
        if sha:
            by_sha[sha].append(i)
    rep_of: dict[int, int] = {}
    for ids in by_sha.values():
        if len(ids) > 1:
            ids.sort(key=order)
            group("exact", ids[0], [(m, None) for m in ids[1:]], True)
            counts["extra_bytes"] += sum(byid[m].size for m in ids[1:])
            for m in ids[1:]:
                rep_of[m] = ids[0]

    # near (one representative per exact group)
    if near:
        photos = sorted(
            (i for i, r in byid.items() if r.kind == "photo" and i not in rep_of
             and info.get(i, ("", ""))[1]),
            key=order,
        )  # fmt: skip
        tree = _BKTree()
        parent: dict[int, int] = {}
        dist: dict[int, int] = {}
        for i in photos:  # best first, so the first member of a cluster is its keep
            v = int(info[i][1], 16)
            best = min(tree.near(v, near_distance), key=lambda t: (t[1], t[0]), default=None)
            if best is None:
                tree.add(v, i)
                parent[i] = i
            else:
                parent[i], dist[i] = parent[best[0]], best[1]
        clusters: dict[int, list[int]] = defaultdict(list)
        for i, p in parent.items():
            if i != p:
                clusters[p].append(i)
        for keep, members in clusters.items():
            group("near", keep, [(m, dist[m]) for m in members], True)

    # album copies (Takeout): the copy points at the "Photos from YYYY" file
    main_by_path: dict[tuple[str, str], int] = {
        (r.root, r.rel_path): r.id for r in rows if r.source == "takeout"
    }
    copies: dict[int, list[int]] = defaultdict(list)
    for r in _rows(con, "AND album_copy_of!=''"):
        orig = main_by_path.get((r.root, r.album_copy_of))
        if orig:
            copies[orig].append(r.id)
    for orig, cs in copies.items():
        group("album_copy", orig, [(c, None) for c in cs], True)

    # -edited pairs: same folder, same original name; both kept
    originals: dict[tuple[str, str, str], int] = {}
    for r in rows:
        if r.source == "takeout" and not r.is_edited:
            originals[(r.root, dirname(r.rel_path), r.name)] = r.id
    for r in rows:
        if r.is_edited:
            base, _, _ = _media_key(r.name)
            orig = originals.get((r.root, dirname(r.rel_path), base))
            if orig:
                group("edited", r.id, [(orig, None)], False)

    con.execute(
        "UPDATE dup_runs SET finished_at=?, counts=? WHERE id=?",
        (time.time(), json.dumps(counts), run_id),
    )
    con.commit()
    if on_progress:
        on_progress(dict(hc))
    return DupResult(run_id, counts)


def groups(con: sqlite3.Connection, run_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    """Groups of a run, each with its files (keep first)."""
    ensure_schema(con)
    q = (
        "SELECT g.id, g.kind, i.role, i.distance, m.id, m.container, m.rel_path, m.size "
        "FROM dup_groups g JOIN dup_items i ON i.group_id=g.id JOIN media m ON m.id=i.media_id "
        "WHERE g.run_id=?" + (" AND g.kind=?" if kind else "") +
        " ORDER BY g.id, i.role DESC, m.id"
    )  # fmt: skip
    out: dict[int, dict[str, Any]] = {}
    for gid, k, role, d, mid, cont, rel, size in con.execute(
        q, (run_id, kind) if kind else (run_id,)
    ):
        g = out.setdefault(gid, {"group": gid, "kind": k, "files": []})
        g["files"].append({"media_id": mid, "role": role, "distance": d,
                           "container": cont, "rel_path": rel, "size": size})  # fmt: skip
    return list(out.values())
