"""Background jobs for the local API: one long step at a time, with live progress.

A job runs one step from `app.pipeline.steps` in a worker thread with its own SQLite
connection. Progress from the step's batches is kept in memory (for the SSE stream) and saved
to the `jobs` table about once a second. Stop is cooperative: the next batch boundary raises
`JobStopped`; work already committed stays, and running the same step again resumes.
If the app closes mid-job, that job is marked `stopped` on the next start.
"""

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core import plans
from app.core.config import settings
from app.db import store
from app.pipeline import steps

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,          -- running | done | failed | stopped
    progress TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL,
    finished_at REAL
);
"""
SAVE_EVERY = 1.0  # seconds between progress writes to the database


class JobStopped(Exception):
    """Raised inside a step at a batch boundary when the user asked to stop."""


class Busy(Exception):
    """Another job is still running."""


@dataclass
class Job:
    id: int
    kind: str
    params: dict[str, Any]
    status: str = "running"
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    seq: int = 0  # bumps on every change; the SSE stream sends when it moves
    stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def view(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "id", "kind", "params", "status", "progress", "result", "error",
            "started_at", "finished_at")}  # fmt: skip


def _step(kind: str, p: dict[str, Any]) -> Callable[..., dict[str, Any]]:
    """Validate params and return fn(con, on_progress=...) for one job kind."""
    bs = settings.batch_size
    if kind == "import_takeout":
        paths = [Path(x) for x in p.get("paths") or []]
        if not paths:
            raise ValueError("paths: give at least one Takeout zip or folder")
        return lambda con, on_progress: steps.import_takeout(
            con, paths, batch_size=bs, on_progress=on_progress)  # fmt: skip
    if kind == "import_folder":
        if not p.get("path"):
            raise ValueError("path: give a folder")
        path = Path(p["path"])
        return lambda con, on_progress: steps.import_folder(
            con, path, batch_size=bs, on_progress=on_progress)  # fmt: skip
    if kind == "dates":
        return lambda con, on_progress: steps.dates(con, batch_size=bs, on_progress=on_progress)
    if kind == "dupes":
        near, dist = bool(p.get("near", True)), p.get("distance")
        if dist is not None and not (isinstance(dist, int) and 0 <= dist <= 32):
            raise ValueError("distance: whole number 0..32")
        return lambda con, on_progress: steps.dupes(
            con, near=near, distance=dist, batch_size=bs, on_progress=on_progress)  # fmt: skip
    if kind == "solo":
        name, photo = str(p.get("name") or "").strip(), p.get("photo")
        if not name or not photo:
            raise ValueError("name and photo are required")
        thr = p.get("threshold")
        return lambda con, on_progress: steps.solo(
            con, name=name, photo=Path(photo), models_dir=settings.models_dir,
            tagged_only=bool(p.get("tagged_only")), threshold=thr,
            batch_size=bs, on_progress=on_progress)  # fmt: skip
    if kind in ("apply_plan", "undo_plan"):
        pid, code = p.get("plan"), str(p.get("code") or "")
        if not isinstance(pid, int) or not code:
            raise ValueError(
                "plan (id) and code (the confirm code shown with the list) are required"
            )
        fn = plans.apply if kind == "apply_plan" else plans.undo
        con = store.connect(settings.db_path)
        try:  # wrong code or wrong state: refuse before any job starts
            plans.check(con, pid, code, for_undo=kind == "undo_plan")
        except plans.PlanError as e:
            raise ValueError(str(e)) from e
        finally:
            con.close()

        def check_then_run(con: sqlite3.Connection, on_progress: Any) -> dict[str, Any]:
            return fn(con, pid, code, log_path=settings.undo_log_path, batch_size=bs,
                      on_progress=on_progress)  # fmt: skip

        return check_then_run
    raise ValueError(f"unknown job kind: {kind}")


KINDS = ("import_takeout", "import_folder", "dates", "dupes", "solo", "apply_plan", "undo_plan")


class JobManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._jobs: dict[int, Job] = {}
        self._current: Job | None = None
        con = self._con()
        try:
            con.execute(
                "UPDATE jobs SET status='stopped', error='app closed while running; run it again "
                "to resume', finished_at=? WHERE status='running'",
                (time.time(),),
            )
            con.commit()
        finally:
            con.close()

    def _con(self) -> sqlite3.Connection:
        con = store.connect(self.db_path)
        con.executescript(SCHEMA)
        return con

    # ---- public ----
    def start(self, kind: str, params: dict[str, Any] | None = None) -> Job:
        params = params or {}
        fn = _step(kind, params)  # raises ValueError on bad input, before anything starts
        with self._lock:
            if self._current and self._current.status == "running":
                raise Busy(f"job {self._current.id} ({self._current.kind}) is still running")
            con = self._con()
            try:
                jid = con.execute(
                    "INSERT INTO jobs (kind, params, status, started_at) VALUES (?,?,?,?)",
                    (kind, json.dumps(params), "running", time.time()),
                ).lastrowid
                con.commit()
            finally:
                con.close()
            assert jid is not None
            job = Job(jid, kind, params)
            self._jobs[jid] = job
            self._current = job
        threading.Thread(target=self._run, args=(job, fn), name=f"job-{jid}", daemon=True).start()
        return job

    def get(self, jid: int) -> Job | None:
        job = self._jobs.get(jid)
        if job:
            return job
        con = self._con()
        try:
            r = con.execute(
                "SELECT id, kind, params, status, progress, result, error, started_at, "
                "finished_at FROM jobs WHERE id=?",
                (jid,),
            ).fetchone()
        finally:
            con.close()
        if not r:
            return None
        return Job(r[0], r[1], json.loads(r[2]), r[3], json.loads(r[4]), json.loads(r[5]),
                   r[6], r[7], r[8])  # fmt: skip

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        con = self._con()
        try:
            ids = [
                r[0] for r in con.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
            ]
        finally:
            con.close()
        return [j.view() for i in ids if (j := self.get(i))]

    def stop(self, jid: int) -> Job | None:
        job = self._jobs.get(jid)
        if job and job.status == "running":
            job.stop.set()
        return job or self.get(jid)

    def wait(self, jid: int, timeout: float = 10.0) -> Job | None:
        """For tests and the CLI: block until the job ends."""
        end = time.time() + timeout
        while time.time() < end:
            j = self._jobs.get(jid)
            if not j or j.status != "running":
                return j or self.get(jid)
            time.sleep(0.02)
        return self._jobs.get(jid)

    # ---- worker ----
    def _run(self, job: Job, fn: Callable[..., dict[str, Any]]) -> None:
        con = self._con()
        last_save = 0.0

        def save() -> None:
            con.execute(
                "UPDATE jobs SET status=?, progress=?, result=?, error=?, finished_at=? WHERE id=?",
                (job.status, json.dumps(job.progress), json.dumps(job.result), job.error,
                 job.finished_at, job.id),
            )  # fmt: skip
            con.commit()

        def on_progress(c: dict[str, int]) -> None:
            nonlocal last_save
            job.progress = dict(c)
            job.seq += 1
            if time.time() - last_save >= SAVE_EVERY:
                save()
                last_save = time.time()
            if job.stop.is_set():
                raise JobStopped

        try:
            job.result = fn(con, on_progress=on_progress)
            job.status = "done"
        except JobStopped:
            job.status, job.error = "stopped", "stopped by you; run it again to resume"
        except Exception as e:  # report, never crash the app
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"[:500]
        finally:
            job.finished_at = time.time()
            job.seq += 1
            try:
                save()
            finally:
                con.close()


_manager: JobManager | None = None
_mlock = threading.Lock()


def manager() -> JobManager:
    """One manager per process, bound to the current settings' database."""
    global _manager
    with _mlock:
        if _manager is None or _manager.db_path != settings.db_path:
            _manager = JobManager(settings.db_path)
        return _manager
