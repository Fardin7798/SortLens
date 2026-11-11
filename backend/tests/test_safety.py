import json
from pathlib import Path

import pytest

from app.core.safety import ApprovalRequired, planned_action, write_undo_entry


def test_no_action_without_approval() -> None:
    with pytest.raises(ApprovalRequired):
        planned_action(approval_id=None)


def test_undo_entry_written(tmp_path: Path) -> None:
    log = tmp_path / "undo.jsonl"
    write_undo_entry(log, {"op": "move", "src": "a.jpg", "dst": "b.jpg"})
    line = json.loads(log.read_text(encoding="utf-8").strip())
    assert line["op"] == "move" and "at" in line
