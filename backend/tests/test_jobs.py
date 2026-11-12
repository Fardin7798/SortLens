"""Job API + live progress (SSE), on generated files only."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import jobs
from app.core.config import settings
from app.main import app
from app.pipeline import steps


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "batch_size", 2)
    monkeypatch.setattr(jobs, "SAVE_EVERY", 0.0)
    monkeypatch.setattr(jobs, "_manager", None)
    return TestClient(app)


def _folder(tmp: Path, n: int = 5) -> Path:
    d = tmp / "pics"
    d.mkdir()
    for i in range(n):
        (d / f"IMG_2023051{i}_120000.jpg").write_bytes(b"x" * (i + 1))
    return d


def _events(client: TestClient, jid: int) -> list[tuple[str, dict]]:
    out, ev = [], ""
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                out.append((ev, json.loads(line[6:])))
    return out


def test_import_then_dates_with_live_progress(client: TestClient, tmp_path: Path) -> None:
    d = _folder(tmp_path)
    r = client.post("/api/jobs", json={"kind": "import_folder", "params": {"path": str(d)}})
    assert r.status_code == 202
    jid = r.json()["id"]
    ev = _events(client, jid)
    assert ev[-1][0] == "end" and ev[-1][1]["status"] == "done"
    assert ev[-1][1]["result"]["added"] == 5
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "done" and j["progress"]["seen"] == 5

    r = client.post("/api/jobs", json={"kind": "dates"})
    end = _events(client, r.json()["id"])[-1][1]
    assert end["result"]["filename"] == 5
    assert client.get("/api/stats").json()["date_filename"] == 5
    assert [x["kind"] for x in client.get("/api/jobs").json()] == ["dates", "import_folder"]


def test_stop_busy_and_resume_marker(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(con, path, *, batch_size, on_progress):  # type: ignore[no-untyped-def]
        for i in range(1000):
            time.sleep(0.01)
            on_progress({"seen": i})
        return {}

    monkeypatch.setattr(steps, "import_folder", slow)
    jid = client.post("/api/jobs", json={"kind": "import_folder", "params": {"path": "x"}}).json()[
        "id"
    ]
    busy = client.post("/api/jobs", json={"kind": "dates"})
    assert busy.status_code == 409
    time.sleep(0.1)
    assert client.post(f"/api/jobs/{jid}/stop").status_code == 202
    j = jobs.manager().wait(jid)
    assert j and j.status == "stopped" and 0 < j.progress["seen"] < 999
    ev = _events(client, jid)
    assert ev == [("end", ev[0][1])] and ev[0][1]["status"] == "stopped"


def test_bad_input_and_failure(client: TestClient, tmp_path: Path) -> None:
    assert client.post("/api/jobs", json={"kind": "format_disk"}).status_code == 422
    assert client.post("/api/jobs", json={"kind": "import_folder"}).status_code == 422
    assert (
        client.post("/api/jobs", json={"kind": "dupes", "params": {"distance": 99}}).status_code
        == 422
    )
    assert client.get("/api/jobs/999").status_code == 404
    assert client.get("/api/jobs/999/events").status_code == 404
    jid = client.post(
        "/api/jobs", json={"kind": "import_folder", "params": {"path": str(tmp_path / "nope")}}
    ).json()["id"]
    j = jobs.manager().wait(jid)
    assert j and j.status == "failed" and "not a folder" in j.error


def test_app_closed_mid_job_is_marked_stopped(client: TestClient) -> None:
    con = jobs.manager()._con()
    con.execute("INSERT INTO jobs (kind, status, started_at) VALUES ('dates', 'running', 1)")
    con.commit()
    con.close()
    m = jobs.JobManager(settings.db_path)  # a fresh start of the app
    j = m.get(1)
    assert j and j.status == "stopped" and "resume" in j.error


def test_dupes_job(client: TestClient, tmp_path: Path) -> None:
    d = tmp_path / "p"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"same")
    (d / "b.mp4").write_bytes(b"same")
    jobs.manager().wait(
        client.post("/api/jobs", json={"kind": "import_folder", "params": {"path": str(d)}}).json()[
            "id"
        ]
    )
    j = jobs.manager().wait(client.post("/api/jobs", json={"kind": "dupes"}).json()["id"])
    assert j and j.status == "done" and j.result["exact"] == 1
