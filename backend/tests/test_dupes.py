"""Duplicate lists on generated files only."""

import io
import json
import random
import zipfile
from pathlib import Path

from PIL import Image

from app.db import store
from app.importers.folder import scan_folder
from app.importers.takeout import scan_takeout
from app.pipeline import dupes


def picture(seed: int, size: int = 256, quality: int = 90) -> bytes:
    rnd = random.Random(seed)
    small = Image.new("RGB", (8, 8))
    small.putdata([tuple(rnd.randrange(256) for _ in range(3)) for _ in range(64)])
    im = small.resize((size, size), Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _setup(tmp: Path):
    d = tmp / "pics"
    (d / "sub").mkdir(parents=True)
    a = picture(1)
    (d / "a.jpg").write_bytes(a)
    (d / "sub" / "a_copy.jpg").write_bytes(a)
    (d / "b.jpg").write_bytes(picture(2, 512))
    (d / "b_small.jpg").write_bytes(picture(2, 200, quality=60))
    (d / "c.jpg").write_bytes(picture(3))
    (d / "broken.jpg").write_bytes(b"\xff\xd8\xff not a picture at all")
    (d / "clip.mp4").write_bytes(b"\x00\x01" * 5000)
    (d / "sub" / "clip2.mp4").write_bytes(b"\x00\x01" * 5000)

    z = tmp / "takeout-001.zip"
    y = "Takeout/Google Photos/Photos from 2024"
    side = lambda n: json.dumps({"title": n, "photoTakenTime": {"timestamp": "1700000000"}})  # noqa: E731
    with zipfile.ZipFile(z, "w") as w:
        w.writestr(f"{y}/x.jpg", picture(4))
        w.writestr(f"{y}/x.jpg.json", side("x.jpg"))
        w.writestr("Takeout/Google Photos/Trip/x.jpg", picture(4))  # album copy
        w.writestr(f"{y}/y.jpg", picture(5))
        w.writestr(f"{y}/y.jpg.json", side("y.jpg"))
        w.writestr(f"{y}/y-edited.jpg", picture(6))
        w.writestr(f"{y}/gone.jpg", a)  # in Google trash: ignored
        w.writestr(f"{y}/gone.jpg.json", json.dumps(
            {"title": "gone.jpg", "photoTakenTime": {"timestamp": "1"}, "trashed": True}))  # fmt: skip
    con = store.connect(tmp / "s.db")
    store.import_records(con, scan_folder(d), source="folder", root=str(d))
    store.import_records(con, scan_takeout([z]), source="takeout", root=str(tmp))
    return con, d, z


def _names(g: dict) -> list[tuple[str, str]]:
    return [(Path(f["rel_path"]).name, f["role"]) for f in g["files"]]


def test_groups(tmp_path: Path) -> None:
    con, d, z = _setup(tmp_path)
    before = {f: f.read_bytes() for f in [*d.rglob("*"), z] if f.is_file()}
    res = dupes.run(con, batch_size=3)
    by_kind: dict[str, list] = {}
    for g in dupes.groups(con, res.run_id):
        by_kind.setdefault(g["kind"], []).append(sorted(_names(g)))
    assert sorted(by_kind["exact"]) == [
        [("a.jpg", "keep"), ("a_copy.jpg", "extra")],
        [("clip.mp4", "keep"), ("clip2.mp4", "extra")],
    ]
    assert by_kind["near"] == [[("b.jpg", "keep"), ("b_small.jpg", "extra")]]  # bigger kept
    assert by_kind["album_copy"] == [[("x.jpg", "extra"), ("x.jpg", "keep")]]
    assert by_kind["edited"] == [[("y-edited.jpg", "keep"), ("y.jpg", "keep")]]
    c = res.counts
    assert (c["exact"], c["near"], c["album_copy"], c["edited"], c["extra_files"]) == (
        2,
        1,
        1,
        1,
        4,
    )
    assert c["extra_bytes"] == len(picture(1)) + 10000
    # sizes that match nothing are never fully hashed
    sha = dict(con.execute(
        "SELECT m.name, h.sha256 FROM file_hashes h JOIN media m ON m.id=h.media_id"))  # fmt: skip
    assert sha["c.jpg"] == "" and sha["a.jpg"] != ""
    assert c["hash_errors"] == 1  # broken.jpg: logged, run goes on
    assert {f: f.read_bytes() for f in before} == before


def test_resume_uses_cache_and_near_off(tmp_path: Path) -> None:
    con, _, _ = _setup(tmp_path)
    first = dupes.run(con).counts
    second = dupes.run(con).counts
    assert second["hash_hashed"] == 0 and second["hash_cached"] == first["hash_todo"]
    assert {k: second[k] for k in ("exact", "near")} == {"exact": 2, "near": 1}
    assert dupes.run(con, near=False).counts["near"] == 0


def test_near_threshold() -> None:
    t = dupes._BKTree()
    for i, v in enumerate([0, 0b111, 0xFFFF]):
        t.add(v, i)
    assert sorted(t.near(0b1, 2)) == [(0, 1), (1, 2)]
    assert list(t.near(0xFFFF, 0)) == [(2, 0)]
