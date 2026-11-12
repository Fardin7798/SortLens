import ast
import json
from pathlib import Path

import pytest

from app.core.safety import Approval, ApprovalRequired, free_name, move_file, write_undo_entry

APP = Path(__file__).resolve().parents[1] / "app"


def test_no_move_without_approval(tmp_path: Path) -> None:
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x")
    for bad in (None, Approval(1, "")):
        with pytest.raises(ApprovalRequired):
            move_file(f, tmp_path / "b.jpg", approval=bad, log_path=tmp_path / "u.jsonl", note={})
    assert f.read_bytes() == b"x" and not (tmp_path / "u.jsonl").exists()


def test_move_logs_first_and_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"new")
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "a.jpg").write_bytes(b"old")
    log = tmp_path / "u.jsonl"
    got = move_file(tmp_path / "a.jpg", tmp_path / "t" / "a.jpg", approval=Approval(7, "c"),
                    log_path=log, note={"item": 1})  # fmt: skip
    assert got == tmp_path / "t" / "a (1).jpg" and got.read_bytes() == b"new"
    assert (tmp_path / "t" / "a.jpg").read_bytes() == b"old"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert [x["phase"] for x in lines] == ["intent", "done"] and lines[0]["plan"] == 7


def test_free_name(tmp_path: Path) -> None:
    assert free_name(tmp_path / "x.jpg") == tmp_path / "x.jpg"


def test_undo_entry_written(tmp_path: Path) -> None:
    log = tmp_path / "undo.jsonl"
    write_undo_entry(log, {"op": "move", "src": "a.jpg", "dst": "b.jpg"})
    line = json.loads(log.read_text(encoding="utf-8").strip())
    assert line["op"] == "move" and "at" in line


def test_no_delete_code_anywhere() -> None:
    """The user's rule: SortLens has no delete. No call that removes files may exist in app/."""
    banned = {"remove", "unlink", "rmtree", "rmdir", "removedirs", "move", "copy", "copy2",
              "copyfile", "truncate"}  # fmt: skip
    found = []
    for py in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in banned:
                    found.append(f"{py.relative_to(APP)}:{node.lineno} {node.func.attr}")
    # The one exception: a half-downloaded face model in SortLens's own data folder.
    assert found == ["pipeline/faces.py:104 unlink"]
    renames = [
        str(py.relative_to(APP))
        for py in APP.rglob("*.py")
        if "os.rename(" in py.read_text(encoding="utf-8")
    ]
    assert renames == ["core/safety.py"]  # the only place that changes user files
