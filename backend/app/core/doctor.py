"""`sortlens doctor`: is this machine ready? Reads only; the data folder is created if missing."""

from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.faces import models_ready

MIN_FREE_GB = 1.0


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def run(data_dir: Path, models_dir: Path, db_path: Path) -> list[Check]:
    out: list[Check] = []
    v = sys.version_info
    out.append(Check("python", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}"))
    out.append(Check("sqlite", True, sqlite3.sqlite_version))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / ".write-test").write_text("ok")  # one tiny file in our own folder
        out.append(Check("data folder", True, str(data_dir)))
    except OSError as e:
        out.append(Check("data folder", False, f"{data_dir}: {e}"))
        return out
    free = shutil.disk_usage(data_dir).free / 1e9
    out.append(Check("free space", free >= MIN_FREE_GB, f"{free:.1f} GB"))
    out.append(
        Check("database", True, str(db_path) if db_path.exists() else "new (created on first use)")
    )
    for mod, label in (
        ("PIL", "pillow"),
        ("pillow_heif", "HEIC support"),
        ("imagehash", "imagehash"),
    ):
        found = importlib.util.find_spec(mod) is not None
        out.append(Check(label, found, "installed" if found else "missing"))
    cv = importlib.util.find_spec("cv2") is not None
    out.append(
        Check(
            "faces (solo list)",
            cv,
            "installed" if cv else "not installed: setup without -NoFaces",
            False,
        )
    )
    if cv:
        ready = models_ready(models_dir)
        out.append(
            Check(
                "face models", ready, "ready" if ready else "run: sortlens models download", False
            )
        )
    return out


def report(checks: list[Check]) -> tuple[str, bool]:
    lines = []
    for c in checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "warn")
        lines.append(f"{mark}  {c.name:<18} {c.detail}")
    good = all(c.ok for c in checks if c.required)
    lines.append("READY" if good else "NOT READY: fix the FAIL lines above")
    return "\n".join(lines), good
