"""Face detection + face embeddings on CPU, saved per photo so runs can resume.

Engine: OpenCV YuNet (detector, MIT) + SFace (recognizer, Apache-2.0) from opencv_zoo.
Both are small ONNX files that run on a plain laptop CPU (no GPU). This step only READS
photos and writes rows to the SortLens database.
"""

import hashlib
import io
import math
import sqlite3
import time
import urllib.request
from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.media_io import read_bytes

MODELS = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "recognizer": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}
# Cosine similarity at or above this = same person (SFace authors' threshold).
SAME_PERSON = 0.363
MAX_SIDE = 1280  # photos are shrunk to this before detection: faster on an i3, still finds faces

SCHEMA = """
CREATE TABLE IF NOT EXISTS face_scan (
    media_id INTEGER PRIMARY KEY,
    engine TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL,          -- ok | error
    error TEXT NOT NULL DEFAULT '',
    n_faces INTEGER NOT NULL DEFAULT 0,
    scanned_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY,
    media_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,  -- 0..1 of the photo
    score REAL NOT NULL,
    embedding BLOB NOT NULL,       -- float32, L2-normalised
    UNIQUE (media_id, idx)
);
CREATE INDEX IF NOT EXISTS faces_media ON faces(media_id);
"""


@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float
    score: float
    embedding: list[float]


class FaceEngine(Protocol):
    version: str

    def faces(self, data: bytes) -> list[Face]: ...


def normalise(v: Iterable[float]) -> list[float]:
    v = list(v)
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def models_ready(models_dir: Path) -> bool:
    return all((models_dir / name).is_file() for name, _, _ in MODELS.values())


def download_models(models_dir: Path) -> list[Path]:
    """Fetch the two ONNX files once and check their SHA-256. Skips files already correct."""
    models_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for name, url, sha in MODELS.values():
        path = models_dir / name
        if not (path.is_file() and _sha256(path) == sha):
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)  # noqa: S310 (fixed https URL)
            if _sha256(tmp) != sha:
                tmp.unlink()
                raise RuntimeError(f"checksum mismatch for {name}; not saved")
            tmp.replace(path)
        out.append(path)
    return out


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OpenCVEngine:
    """YuNet + SFace through OpenCV. Needs `pip install sortlens[faces]` and the model files."""

    version = "yunet2023mar+sface2021dec"

    def __init__(self, models_dir: Path, min_score: float = 0.8) -> None:
        import cv2  # optional dependency, imported only when faces are used

        if not models_ready(models_dir):
            raise FileNotFoundError(
                f"face models missing in {models_dir}; run `sortlens models download`"
            )
        self._cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(
            str(models_dir / MODELS["detector"][0]), "", (320, 320), min_score
        )
        self._rec = cv2.FaceRecognizerSF.create(str(models_dir / MODELS["recognizer"][0]), "")

    def faces(self, data: bytes) -> list[Face]:
        import numpy as np
        from PIL import Image, ImageOps

        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:  # HEIC then fails as a normal decode error
            pass
        with Image.open(io.BytesIO(data)) as raw:
            pic = ImageOps.exif_transpose(raw).convert("RGB")
        pic.thumbnail((MAX_SIDE, MAX_SIDE))
        img = np.ascontiguousarray(np.asarray(pic)[:, :, ::-1])  # RGB -> BGR
        h, w = img.shape[:2]
        self._det.setInputSize((w, h))
        _, found = self._det.detect(img)
        out: list[Face] = []
        for row in found if found is not None else []:
            emb = self._rec.feature(self._rec.alignCrop(img, row)).flatten().tolist()
            x, y, fw, fh = (float(v) for v in row[:4])
            out.append(Face(x / w, y / h, fw / w, fh / h, float(row[-1]), normalise(emb)))
        return out


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def scan(
    con: sqlite3.Connection,
    engine: FaceEngine,
    media_ids: Iterable[int],
    *,
    batch_size: int = 50,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Find faces in these photos. Photos already scanned by this engine (and unchanged) are
    skipped, so stopping and running again carries on where it stopped."""
    ensure_schema(con)
    c = {"todo": 0, "scanned": 0, "skipped": 0, "errors": 0, "faces": 0}
    ids = list(media_ids)
    c["todo"] = len(ids)
    for i in range(0, len(ids), batch_size):
        for mid in ids[i : i + batch_size]:
            m = con.execute(
                "SELECT root, container, rel_path, size, mtime FROM media WHERE id=?", (mid,)
            ).fetchone()
            done = con.execute(
                "SELECT engine, size, mtime FROM face_scan WHERE media_id=?", (mid,)
            ).fetchone()
            if m is None or (done and tuple(done) == (engine.version, m[3], m[4])):
                c["skipped"] += 1
                continue
            con.execute("DELETE FROM faces WHERE media_id=?", (mid,))
            status, err, found = "ok", "", []
            try:
                found = engine.faces(read_bytes(m[0], m[1], m[2]))
            except Exception as e:  # unreadable/corrupt photo: record it, never guess
                status, err = "error", f"{type(e).__name__}: {e}"[:300]
                c["errors"] += 1
            for idx, f in enumerate(found):
                con.execute(
                    "INSERT INTO faces (media_id, idx, x, y, w, h, score, embedding) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (mid, idx, f.x, f.y, f.w, f.h, f.score, array("f", f.embedding).tobytes()),
                )
            con.execute(
                "INSERT OR REPLACE INTO face_scan VALUES (?,?,?,?,?,?,?,?)",
                (mid, engine.version, m[3], m[4], status, err, len(found), time.time()),
            )
            c["scanned"] += 1
            c["faces"] += len(found)
        con.commit()
        if on_progress:
            on_progress(c)
    return c


def faces_of(con: sqlite3.Connection, media_id: int) -> list[list[float]]:
    rows = con.execute(
        "SELECT embedding FROM faces WHERE media_id=? ORDER BY idx", (media_id,)
    ).fetchall()
    return [list(array("f", r[0])) for r in rows]


def scan_status(con: sqlite3.Connection, media_id: int) -> Any:
    return con.execute("SELECT status FROM face_scan WHERE media_id=?", (media_id,)).fetchone()
