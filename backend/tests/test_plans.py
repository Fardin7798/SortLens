"""Review plans: list first, code required, trash instead of delete, undo. Generated files."""

import json
import zipfile
from pathlib import Path

import pytest

from app.core import plans
from app.core.safety import CrossDrive
from app.db import store
from app.importers.folder import scan_folder
from app.importers.takeout import scan_takeout
from app.pipeline import dupes

TRASH = "SortLens Trash"


def _setup(tmp: Path):
    root = tmp / "Photos"
    (root / "2023").mkdir(parents=True)
    (root / "2023" / "a.jpg").write_bytes(b"same-bytes")
    (root / "2023" / "a copy.jpg").write_bytes(b"same-bytes")
    (root / "b.jpg").write_bytes(b"b")
    con = store.connect(tmp / "s.db")
    store.import_records(con, scan_folder(root), source="folder", root=str(root))
    return con, root


def _ids(con, *names: str) -> list[int]:
    return [con.execute("SELECT id FROM media WHERE name=?", (n,)).fetchone()[0] for n in names]


def test_trash_plan_apply_and_undo(tmp_path: Path) -> None:
    con, root = _setup(tmp_path)
    log = tmp_path / "undo.jsonl"
    run = dupes.run(con, near=False).run_id
    pid = plans.from_dupes(con, run)
    p = plans.get(con, pid)
    assert p and p["status"] == "ready" and len(p["items"]) == 1
    item = p["items"][0]
    extra = Path(item["src"])
    assert item["dst"] == str(root / TRASH / extra.relative_to(root))
    assert extra.exists()  # making a plan moves nothing

    with pytest.raises(plans.PlanError):
        plans.apply(con, pid, "wrong", log_path=log)
    assert extra.exists() and not log.exists()

    c = plans.apply(con, pid, p["code"], log_path=log)
    assert c["moved"] == 1 and not extra.exists()
    trashed = root / TRASH / extra.relative_to(root)
    assert trashed.read_bytes() == b"same-bytes"
    assert store.stats(con)["in_sortlens_trash"] == 1
    # trash is invisible to scans and to the next duplicate run
    store.import_records(con, scan_folder(root), source="folder", root=str(root))
    assert store.stats(con)["total"] == 3
    assert dupes.run(con, near=False).counts["exact"] == 0
    with pytest.raises(plans.PlanError):  # applied once only
        plans.apply(con, pid, p["code"], log_path=log)

    u = plans.undo(con, pid, p["code"], log_path=log)
    assert u["restored"] == 1 and extra.read_bytes() == b"same-bytes" and not trashed.exists()
    assert store.stats(con)["in_sortlens_trash"] == 0
    assert plans.get(con, pid)["status"] == "undone"  # type: ignore[index]
    ops = [json.loads(x) for x in log.read_text().splitlines()]
    assert [(o["phase"], bool(o.get("undo"))) for o in ops] == [
        ("intent", False), ("done", False), ("intent", True), ("done", True)]  # fmt: skip


def test_move_solo_style_list_and_rules(tmp_path: Path) -> None:
    con, root = _setup(tmp_path)
    log = tmp_path / "undo.jsonl"
    (root / "Fardin akela").mkdir()
    (root / "Fardin akela" / "b.jpg").write_bytes(b"already here, other photo")
    a, b = _ids(con, "a.jpg", "b.jpg")
    pid = plans.create(con, [a, b], kind="move", dest=Path("Fardin akela"))
    p = plans.get(con, pid)
    assert p
    plans.apply(con, pid, p["code"], log_path=log)
    assert (root / "Fardin akela" / "a.jpg").read_bytes() == b"same-bytes"
    assert (root / "Fardin akela" / "b (1).jpg").read_bytes() == b"b"  # never overwrites
    assert (root / "Fardin akela" / "b.jpg").read_bytes() == b"already here, other photo"
    rel = dict(con.execute("SELECT name, rel_path FROM media"))
    assert rel["b.jpg"] == "Fardin akela/b (1).jpg"
    plans.undo(con, pid, p["code"], log_path=log)
    assert (root / "b.jpg").read_bytes() == b"b" and (root / "2023" / "a.jpg").exists()

    outside = plans.get(con, plans.create(con, [a], kind="move", dest=tmp_path / "elsewhere"))
    assert outside and outside["items"][0]["action"] == "skip"
    assert "outside" in outside["items"][0]["note"]
    with pytest.raises(plans.PlanError):
        plans.create(con, [], kind="trash")
    with pytest.raises(plans.PlanError):
        plans.create(con, [a], kind="delete")


def test_changed_file_is_not_moved_and_stop_resume(tmp_path: Path) -> None:
    con, root = _setup(tmp_path)
    log = tmp_path / "undo.jsonl"
    a, b = _ids(con, "a.jpg", "b.jpg")
    pid = plans.create(con, [a, b], kind="trash")
    code = plans.get(con, pid)["code"]  # type: ignore[index]
    (root / "b.jpg").write_bytes(b"edited by the user after the scan")
    c = plans.apply(con, pid, code, log_path=log)
    assert c == {"todo": 2, "moved": 1, "marked": 0, "failed": 1}
    assert (root / "b.jpg").exists() and plans.get(con, pid)["status"] == "partial"  # type: ignore[index]

    # app stopped right after a move, before the database knew: the undo log finishes it
    pid2 = plans.create(con, _ids(con, "a copy.jpg"), kind="trash")
    p2 = plans.get(con, pid2)
    assert p2
    from app.core.safety import Approval, move_file

    it = p2["items"][0]
    move_file(Path(it["src"]), Path(it["dst"]), approval=Approval(pid2, p2["code"]),
              log_path=log, note={"item": it["id"], "media": it["media_id"]})  # fmt: skip
    c2 = plans.apply(con, pid2, p2["code"], log_path=log)
    assert c2["moved"] == 1 and c2["failed"] == 0
    assert plans.get(con, pid2)["items"][0]["note"].startswith("finished after a stop")  # type: ignore[index]


def test_zip_files_are_only_marked(tmp_path: Path) -> None:
    z = tmp_path / "takeout-001.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("Takeout/Google Photos/Photos from 2024/x.jpg", b"x")
    con = store.connect(tmp_path / "s.db")
    store.import_records(con, scan_takeout([z]), source="takeout", root=str(tmp_path))
    before = z.read_bytes()
    pid = plans.create(con, _ids(con, "x.jpg"), kind="trash")
    p = plans.get(con, pid)
    assert p and p["items"][0]["action"] == "mark"
    assert plans.apply(con, pid, p["code"], log_path=tmp_path / "u")["marked"] == 1
    assert z.read_bytes() == before and store.stats(con)["marked_in_zip"] == 1
    plans.undo(con, pid, p["code"], log_path=tmp_path / "u")
    assert store.stats(con)["marked_in_zip"] == 0


def test_takeout_folder_sidecar_moves_with_photo(tmp_path: Path) -> None:
    t = tmp_path / "Takeout"
    y = t / "Google Photos" / "Photos from 2024"
    y.mkdir(parents=True)
    (y / "p.jpg").write_bytes(b"p")
    (y / "p.jpg.json").write_text(
        json.dumps({"title": "p.jpg", "photoTakenTime": {"timestamp": "1"}})
    )
    con = store.connect(tmp_path / "s.db")
    store.import_records(con, scan_takeout([t]), source="takeout", root=str(t))
    pid = plans.create(con, _ids(con, "p.jpg"), kind="trash")
    p = plans.get(con, pid)
    assert p and p["items"][0]["sidecar_src"]
    plans.apply(con, pid, p["code"], log_path=tmp_path / "u")
    tr = t / TRASH / "Google Photos" / "Photos from 2024"
    assert (
        (tr / "p.jpg").exists() and (tr / "p.jpg.json").exists() and not (y / "p.jpg.json").exists()
    )
    plans.undo(con, pid, p["code"], log_path=tmp_path / "u")
    assert (y / "p.jpg").exists() and (y / "p.jpg.json").exists()


def test_cross_drive_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import safety

    monkeypatch.setattr(safety, "_device", lambda p: 2 if p.name == "T" else 1)
    f = tmp_path / "a.jpg"
    f.write_bytes(b"a")
    with pytest.raises(CrossDrive):
        safety.move_file(f, tmp_path / "T" / "a.jpg", approval=safety.Approval(1, "c"),
                         log_path=tmp_path / "u", note={})  # fmt: skip
    assert f.exists()
