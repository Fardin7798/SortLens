"""Review plans: the only way a file ever moves.

1. `create_*` builds a plan (rows only, nothing on disk changes) and gives it a confirm code.
2. The user sees the FULL list (`plan_items`, CLI `plan-show`, API `GET /api/plans/{id}`).
3. `apply(code)` moves the files: the code must match the plan, so the user approved exactly
   this list. `undo(code)` moves every done file back.

Kinds:
  trash  "delete" = move into `<location>/SortLens Trash/<same sub-path>`. Never a real delete.
  move   move into a folder the user chose, inside the same location (e.g. a solo list).
Files inside a Takeout zip cannot move; they get a mark (`media.user_mark`) instead.
A Takeout sidecar JSON moves with its photo, unless another file still uses it.
"""

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.safety import Approval, move_file
from app.importers.base import TRASH_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,            -- trash | move
    title TEXT NOT NULL DEFAULT '',
    dest TEXT NOT NULL DEFAULT '', -- move: the chosen folder
    code TEXT NOT NULL,
    status TEXT NOT NULL,          -- ready | applied | partial | undone
    created_at REAL NOT NULL,
    applied_at REAL,
    undone_at REAL
);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL,
    media_id INTEGER NOT NULL,
    src TEXT NOT NULL,             -- full path now ('' for a file inside a zip)
    dst TEXT NOT NULL,             -- planned full path; after apply: where it really went
    sidecar_src TEXT NOT NULL DEFAULT '',
    sidecar_dst TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,          -- move | mark | skip
    status TEXT NOT NULL,          -- pending | done | skipped | failed | undone
    note TEXT NOT NULL DEFAULT ''
);
"""

Progress = Callable[[dict[str, int]], None] | None


class PlanError(ValueError):
    """Bad plan request, wrong confirm code, or a plan in the wrong state."""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _media(con: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    try:
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            out += con.execute(
                f"SELECT * FROM media WHERE id IN ({','.join('?' * len(chunk))})", chunk
            ).fetchall()
        return sorted(out, key=lambda r: ids.index(r["id"]) if len(ids) < 5000 else r["id"])
    finally:
        con.row_factory = None


def _sidecar_shared(con: sqlite3.Connection, r: sqlite3.Row, ids: set[int]) -> bool:
    others = [
        x[0]
        for x in con.execute(
            "SELECT id FROM media WHERE root=? AND container='' AND sidecar=? AND id!=?",
            (r["root"], r["sidecar"], r["id"]),
        )
    ]
    return any(o not in ids for o in others)


def _code(kind: str, items: list[tuple[Any, ...]]) -> str:
    h = hashlib.sha256(json.dumps([kind, items], ensure_ascii=False).encode())
    return h.hexdigest()[:8]


def create(
    con: sqlite3.Connection,
    media_ids: list[int],
    *,
    kind: str,
    dest: Path | None = None,
    title: str = "",
) -> int:
    """Write a plan for these files. Changes nothing on disk."""
    ensure_schema(con)
    if kind not in ("trash", "move"):
        raise PlanError("kind must be trash or move")
    if kind == "move" and not dest:
        raise PlanError("move needs a destination folder")
    ids = list(dict.fromkeys(media_ids))
    if not ids:
        raise PlanError("the list is empty")
    rows = _media(con, ids)
    if len(rows) != len(ids):
        raise PlanError("some files are not in the database")
    idset = set(ids)
    items: list[tuple[Any, ...]] = []
    for r in rows:
        root = Path(r["root"])
        side_src = side_dst = ""
        if r["container"]:
            action, src, dst = "mark", "", ""
            note = "inside a Takeout zip: cannot be moved, it will only be marked"
        elif r["in_trash"]:
            action, src, dst, note = (
                "skip",
                str(root / r["rel_path"]),
                "",
                "already in SortLens Trash",
            )
        else:
            src_p = root / r["rel_path"]
            if kind == "trash":
                dst_p = root / TRASH_DIR / r["rel_path"]
            else:
                assert dest is not None
                d = dest if dest.is_absolute() else root / dest
                dst_p = d / r["name"]
            action, note = "move", ""
            if kind == "move" and not dst_p.resolve().is_relative_to(root.resolve()):
                action, note = "skip", "destination is outside this location"
            elif kind == "move" and TRASH_DIR in dst_p.relative_to(root).parts:
                action, note = "skip", "destination is inside SortLens Trash"
            elif dst_p.parent.resolve() == src_p.parent.resolve():
                action, note = "skip", "already in that folder"
            src, dst = str(src_p), str(dst_p) if action == "move" else ""
            if action == "move" and r["sidecar"]:
                if _sidecar_shared(con, r, idset):
                    note = "sidecar JSON stays: another file uses it"
                else:
                    side_src = str(root / r["sidecar"])
                    side_dst = str(dst_p.parent / Path(r["sidecar"]).name)
        items.append((r["id"], src, dst, side_src, side_dst, action, note))
    code = _code(kind, items)
    pid = con.execute(
        "INSERT INTO plans (kind, title, dest, code, status, created_at) VALUES (?,?,?,?,?,?)",
        (kind, title, str(dest or ""), code, "ready", time.time()),
    ).lastrowid
    con.executemany(
        "INSERT INTO plan_items (plan_id, media_id, src, dst, sidecar_src, sidecar_dst, action, "
        "status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        [(pid, *it[:6], "skipped" if it[5] == "skip" else "pending", it[6]) for it in items],
    )
    con.commit()
    assert pid is not None
    return pid


def from_solo(
    con: sqlite3.Connection, run_id: int, *, dest: Path, buckets: tuple[str, ...] = ("solo",)
) -> int:
    ids = [
        r[0]
        for r in con.execute(
            f"SELECT media_id FROM solo_items WHERE run_id=? AND bucket IN "
            f"({','.join('?' * len(buckets))}) ORDER BY media_id",
            (run_id, *buckets),
        )
    ]
    return create(con, ids, kind="move", dest=dest, title=f"solo list {run_id} -> {dest}")


def from_dupes(con: sqlite3.Connection, run_id: int, *, kinds: tuple[str, ...] = ("exact",)) -> int:
    """Trash plan for the `extra` files of a duplicate run (the suggested keeps stay)."""
    ids = [
        r[0]
        for r in con.execute(
            "SELECT i.media_id FROM dup_items i JOIN dup_groups g ON g.id=i.group_id "
            f"WHERE g.run_id=? AND i.role='extra' AND g.kind IN ({','.join('?' * len(kinds))}) "
            "ORDER BY i.media_id",
            (run_id, *kinds),
        )
    ]
    return create(con, ids, kind="trash", title=f"duplicates {run_id} ({', '.join(kinds)})")


def get(con: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
    ensure_schema(con)
    con.row_factory = sqlite3.Row
    try:
        p = con.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not p:
            return None
        items = [
            dict(r)
            for r in con.execute(
                "SELECT i.*, m.name, m.container, m.rel_path FROM plan_items i "
                "JOIN media m ON m.id=i.media_id WHERE i.plan_id=? ORDER BY i.id",
                (plan_id,),
            )
        ]
    finally:
        con.row_factory = None
    counts: dict[str, int] = {}
    for it in items:
        counts[f"{it['action']}_{it['status']}"] = (
            counts.get(f"{it['action']}_{it['status']}", 0) + 1
        )
    return {**dict(p), "counts": counts, "items": items}


def recent(con: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    ensure_schema(con)
    rows = con.execute(
        "SELECT id, kind, title, status, created_at FROM plans ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        dict(zip(("id", "kind", "title", "status", "created_at"), r, strict=True)) for r in rows
    ]


def _approve(
    con: sqlite3.Connection, plan_id: int, code: str, states: tuple[str, ...]
) -> sqlite3.Row:
    ensure_schema(con)
    con.row_factory = sqlite3.Row
    try:
        p = con.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    finally:
        con.row_factory = None
    if not p:
        raise PlanError("no such plan")
    if not code or code.strip().lower() != p["code"]:
        raise PlanError("confirm code does not match this plan; show the list and use its code")
    if p["status"] not in states:
        raise PlanError(f"plan is {p['status']}")
    return p


def check(con: sqlite3.Connection, plan_id: int, code: str, *, for_undo: bool = False) -> None:
    """Raise PlanError unless the code matches and the plan can be applied (or undone)."""
    _approve(con, plan_id, code, ("applied", "partial") if for_undo else ("ready", "partial"))


def _logged_moves(log_path: Path, plan_id: int) -> dict[int, dict[str, str]]:
    """Finished moves of a plan from the undo log: item id -> {"file": dst, "sidecar": dst}.
    Used when the app stopped between a move and its database update."""
    out: dict[int, dict[str, str]] = {}
    if not log_path.exists():
        return out
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("plan") == plan_id and e.get("phase") == "done" and "item" in e:
                slot = out.setdefault(int(e["item"]), {})
                key = "sidecar" if e.get("sidecar") else "file"
                if e.get("undo"):
                    slot.pop(key, None)
                else:
                    slot[key] = str(e["dst"])
    return out


def _rel(root: str, path: str) -> str:
    return Path(path).relative_to(Path(root)).as_posix()


class _AlreadyDone(Exception):
    pass


def _record_move(
    con: sqlite3.Connection, mid: int, root: str, dst: str, sidecar_dst: str, trash: bool
) -> None:
    con.execute(
        "UPDATE media SET rel_path=?, in_trash=?, sidecar=CASE WHEN ?!='' THEN ? "
        "ELSE sidecar END WHERE id=?",
        (
            _rel(root, dst),
            int(trash),
            sidecar_dst,
            _rel(root, sidecar_dst) if sidecar_dst else "",
            mid,
        ),
    )


def apply(
    con: sqlite3.Connection,
    plan_id: int,
    code: str,
    *,
    log_path: Path,
    batch_size: int = 50,
    on_progress: Progress = None,
) -> dict[str, int]:
    """Carry out an approved plan. Safe to run again after a stop: done items are kept."""
    p = _approve(con, plan_id, code, ("ready", "partial"))
    ok = Approval(plan_id, p["code"])
    todo = con.execute(
        "SELECT i.id, i.media_id, i.src, i.dst, i.sidecar_src, i.sidecar_dst, i.action, m.root, "
        "m.size, m.mtime FROM plan_items i JOIN media m ON m.id=i.media_id "
        "WHERE i.plan_id=? AND i.status IN ('pending','failed') ORDER BY i.id",
        (plan_id,),
    ).fetchall()
    c = {"todo": len(todo), "moved": 0, "marked": 0, "failed": 0}
    logged = _logged_moves(log_path, plan_id) if todo else {}
    for n, (iid, mid, src, dst, ssrc, sdst, action, root, size, mtime) in enumerate(todo, 1):
        status, note, real_dst, real_sdst = "done", "", dst, sdst
        if action == "mark":
            con.execute("UPDATE media SET user_mark=? WHERE id=?", (p["kind"], mid))
            c["marked"] += 1
        else:
            s = Path(src)
            try:
                prev = logged.get(iid, {})
                if not s.exists() and prev.get("file") and Path(prev["file"]).is_file():
                    real_dst, real_sdst = prev["file"], prev.get("sidecar", "")
                    _record_move(con, mid, root, real_dst, real_sdst, p["kind"] == "trash")
                    c["moved"] += 1
                    raise _AlreadyDone
                st = s.stat()
                if st.st_size != size or abs(st.st_mtime - mtime) > 2:
                    raise RuntimeError("file changed since it was scanned; scan again first")
                note_ = {"item": iid, "media": mid}
                real_dst = str(move_file(s, Path(dst), approval=ok, log_path=log_path, note=note_))
                if ssrc and Path(ssrc).is_file():
                    real_sdst = str(move_file(Path(ssrc), Path(sdst), approval=ok,
                                              log_path=log_path, note={**note_, "sidecar": True}))  # fmt: skip
                else:
                    real_sdst = ""
                _record_move(con, mid, root, real_dst, real_sdst, p["kind"] == "trash")
                c["moved"] += 1
            except _AlreadyDone:
                note = "finished after a stop (found in the undo log)"
            except Exception as e:  # one bad file never stops the plan
                status, note = "failed", f"{type(e).__name__}: {e}"[:300]
                c["failed"] += 1
        con.execute(
            "UPDATE plan_items SET status=?, note=CASE WHEN ?!='' THEN ? ELSE note END, dst=?, "
            "sidecar_dst=? WHERE id=?",
            (status, note, note, real_dst, real_sdst, iid),
        )
        if n % batch_size == 0:
            con.commit()
            if on_progress:
                on_progress(dict(c))
    left = con.execute(
        "SELECT COUNT(*) FROM plan_items WHERE plan_id=? AND status IN ('pending','failed')",
        (plan_id,),
    ).fetchone()[0]
    con.execute(
        "UPDATE plans SET status=?, applied_at=? WHERE id=?",
        ("partial" if left else "applied", time.time(), plan_id),
    )
    con.commit()
    if on_progress:
        on_progress(dict(c))
    return c


def undo(
    con: sqlite3.Connection,
    plan_id: int,
    code: str,
    *,
    log_path: Path,
    batch_size: int = 50,
    on_progress: Progress = None,
) -> dict[str, int]:
    """Move every done file of a plan back to where it was (newest first)."""
    p = _approve(con, plan_id, code, ("applied", "partial"))
    ok = Approval(plan_id, p["code"])
    done = con.execute(
        "SELECT i.id, i.media_id, i.src, i.dst, i.sidecar_src, i.sidecar_dst, i.action, m.root "
        "FROM plan_items i JOIN media m ON m.id=i.media_id "
        "WHERE i.plan_id=? AND i.status='done' ORDER BY i.id DESC",
        (plan_id,),
    ).fetchall()
    c = {"todo": len(done), "restored": 0, "unmarked": 0, "failed": 0}
    for n, (iid, mid, src, dst, ssrc, sdst, action, root) in enumerate(done, 1):
        status, note = "undone", ""
        if action == "mark":
            con.execute("UPDATE media SET user_mark='' WHERE id=?", (mid,))
            c["unmarked"] += 1
        else:
            try:
                if Path(src).exists():
                    raise FileExistsError(f"something new is at the original place: {src}")
                note_ = {"item": iid, "media": mid, "undo": True}
                back = move_file(Path(dst), Path(src), approval=ok, log_path=log_path, note=note_)
                if sdst and Path(sdst).is_file() and not Path(ssrc).exists():
                    move_file(Path(sdst), Path(ssrc), approval=ok, log_path=log_path,
                              note={**note_, "sidecar": True})  # fmt: skip
                con.execute(
                    "UPDATE media SET rel_path=?, in_trash=0, sidecar=CASE WHEN ?!='' THEN ? "
                    "ELSE sidecar END WHERE id=?",
                    (_rel(root, str(back)), ssrc, _rel(root, ssrc) if ssrc else "", mid),
                )
                c["restored"] += 1
            except Exception as e:
                status, note = "done", f"undo failed: {type(e).__name__}: {e}"[:300]
                c["failed"] += 1
        con.execute(
            "UPDATE plan_items SET status=?, note=CASE WHEN ?!='' THEN ? ELSE note END WHERE id=?",
            (status, note, note, iid),
        )
        if n % batch_size == 0:
            con.commit()
            if on_progress:
                on_progress(dict(c))
    con.execute(
        "UPDATE plans SET status=?, undone_at=? WHERE id=?",
        ("partial" if c["failed"] else "undone", time.time(), plan_id),
    )
    con.commit()
    if on_progress:
        on_progress(dict(c))
    return c
