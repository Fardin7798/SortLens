"""Solo list logic with a fake face engine (no models needed). Generated data only."""

import json
import zipfile
from pathlib import Path

import pytest

from app.db import store
from app.importers.takeout import scan_takeout
from app.pipeline import faces as F
from app.pipeline import solo

ME = [1.0, 0.0, 0.0]
OTHER = [0.0, 1.0, 0.0]
NEAR_ME = F.normalise([0.9, 0.3, 0.0])  # same person, different photo


class FakeEngine:
    """Photo bytes say which faces are in it, e.g. b"me,other". b"bad" = unreadable."""

    version = "fake-1"

    def __init__(self) -> None:
        self.calls = 0

    def faces(self, data: bytes) -> list[F.Face]:
        self.calls += 1
        if data == b"bad":
            raise ValueError("cannot decode")
        table = {"me": ME, "near": NEAR_ME, "other": OTHER}
        return [F.Face(0, 0, 0.1, 0.1, 0.99, table[k]) for k in data.decode().split(",") if k]


def _export(tmp: Path) -> Path:
    z = tmp / "takeout-001.zip"
    y = "Takeout/Google Photos/Photos from 2024"
    photos = {
        "solo_tagged.jpg": (b"me", ["Fardin"]),
        "solo_untagged.jpg": (b"near", []),
        "group.jpg": (b"me,other", ["Fardin", "Ashhal"]),
        "tag_wrong.jpg": (b"other", ["fardin"]),  # tag says him, face says no -> check
        "tag_noface.jpg": (b"", ["Fardin"]),
        "tag_bad.jpg": (b"bad", ["Fardin"]),
        "stranger.jpg": (b"other", []),
        "trashed.jpg": (b"me", ["Fardin"]),
    }
    with zipfile.ZipFile(z, "w") as w:
        for n, (data, people) in photos.items():
            w.writestr(f"{y}/{n}", data)
            side = {
                "title": n,
                "photoTakenTime": {"timestamp": "1700000000"},
                "people": [{"name": p} for p in people],
            }
            if n == "trashed.jpg":
                side["trashed"] = True
            w.writestr(f"{y}/{n}.json", json.dumps(side))
        w.writestr("Takeout/Google Photos/Album/solo_tagged.jpg", b"me")  # album copy: skipped
        w.writestr(f"{y}/clip.mp4", b"me")  # videos are not scanned
    return z


def _db(tmp: Path) -> object:
    con = store.connect(tmp / "s.db")
    store.import_records(con, scan_takeout([_export(tmp)]), source="takeout", root="r")
    return con


def _buckets(con: object, run_id: int) -> dict[str, str]:
    return {r["name"]: r["bucket"] for r in solo.items(con, run_id)}  # type: ignore[arg-type]


def test_solo_group_check_lists(tmp_path: Path) -> None:
    con = _db(tmp_path)
    res = solo.run(con, FakeEngine(), name="Fardin", ref_photo=b"me")  # type: ignore[arg-type]
    assert _buckets(con, res.run_id) == {
        "solo_tagged.jpg": "solo",
        "solo_untagged.jpg": "solo",
        "group.jpg": "group",
        "tag_wrong.jpg": "check",
        "tag_noface.jpg": "check",
        "tag_bad.jpg": "check",
    }
    assert res.counts == {"tagged": 5, "searched_untagged": 2, "solo": 2, "group": 1,
                          "check": 3, "scan_errors": 1}  # fmt: skip
    reasons = {r["name"]: r["reason"] for r in solo.items(con, res.run_id, "check")}  # type: ignore[arg-type]
    assert reasons == {"tag_wrong.jpg": "tagged, face did not match",
                       "tag_noface.jpg": "no face found",
                       "tag_bad.jpg": "photo could not be read"}  # fmt: skip


def test_tagged_only_skips_untagged(tmp_path: Path) -> None:
    con = _db(tmp_path)
    res = solo.run(con, FakeEngine(), name="fardin", ref_photo=b"me", tagged_only=True)  # type: ignore[arg-type]
    b = _buckets(con, res.run_id)
    assert "solo_untagged.jpg" not in b and b["solo_tagged.jpg"] == "solo"


def test_scan_resumes_and_rescans_on_new_engine(tmp_path: Path) -> None:
    con = _db(tmp_path)
    e = FakeEngine()
    solo.run(con, e, name="Fardin", ref_photo=b"me")  # type: ignore[arg-type]
    first = e.calls
    solo.run(con, e, name="Fardin", ref_photo=b"me")  # type: ignore[arg-type]
    assert e.calls - first == 1  # only the reference photo; every candidate was already scanned
    assert first == 8  # 1 reference + 7 candidates
    e2 = FakeEngine()
    e2.version = "fake-2"
    solo.run(con, e2, name="Fardin", ref_photo=b"me")  # type: ignore[arg-type]
    assert e2.calls == 8


def test_reference_must_have_one_face(tmp_path: Path) -> None:
    con = _db(tmp_path)
    for ref in (b"", b"me,other"):
        with pytest.raises(solo.ReferenceError_):
            solo.run(con, FakeEngine(), name="Fardin", ref_photo=ref)  # type: ignore[arg-type]


def test_nothing_touches_the_zip(tmp_path: Path) -> None:
    con = _db(tmp_path)
    z = tmp_path / "takeout-001.zip"
    before = (z.read_bytes(), z.stat().st_mtime)
    solo.run(con, FakeEngine(), name="Fardin", ref_photo=b"me")  # type: ignore[arg-type]
    assert (z.read_bytes(), z.stat().st_mtime) == before


def test_similarity_and_models_list() -> None:
    assert F.similarity(ME, ME) == pytest.approx(1.0)
    assert F.similarity(ME, NEAR_ME) > F.SAME_PERSON > F.similarity(ME, OTHER)
    assert {m[0] for m in F.MODELS.values()} == {
        "face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"}  # fmt: skip
    assert not F.models_ready(Path("/nonexistent"))
