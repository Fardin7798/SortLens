import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Never touch the real ~/.sortlens during tests."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
