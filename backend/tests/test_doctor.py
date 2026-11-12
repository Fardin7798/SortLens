from pathlib import Path

from app.cli import main
from app.core import doctor


def test_doctor_ready_on_fresh_folder(tmp_path: Path) -> None:
    d = tmp_path / "new data"
    checks = doctor.run(d, d / "models", d / "sortlens.db")
    text, good = doctor.report(checks)
    assert good, text
    assert d.is_dir()
    assert "READY" in text


def test_doctor_fails_when_folder_cannot_be_made(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    checks = doctor.run(blocker / "data", blocker / "m", blocker / "db")
    text, good = doctor.report(checks)
    assert not good and "FAIL" in text


def test_doctor_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "d")
    assert main(["doctor"]) == 0
    assert "READY" in capsys.readouterr().out
