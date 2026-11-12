"""Date step on generated files only (folder + Takeout zip)."""

import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pillow_heif
import pytest
from PIL import Image

from app.db import store
from app.importers.folder import scan_folder
from app.importers.takeout import scan_takeout
from app.pipeline.dates import exif_date, filename_date, run_dates

TS = lambda *a: datetime(*a, tzinfo=UTC).timestamp()  # noqa: E731
OLD = TS(2015, 1, 2, 3, 4, 5)


def jpeg(original: str | None = None, offset: str | None = None, digitized: str | None = None):
    im = Image.new("RGB", (8, 8), "red")
    ex = Image.Exif()
    ifd = ex.get_ifd(0x8769)
    if original:
        ifd[36867] = original
    if offset:
        ifd[36881] = offset
    if digitized:
        ifd[36868] = digitized
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=ex)
    return buf.getvalue()


def rows(con) -> dict[str, tuple]:
    q = "SELECT name, taken_at, taken_at_source, taken_at_offset, dates_done_at FROM media"
    return {r[0]: r[1:] for r in con.execute(q)}


def test_exif_and_filename_parsers() -> None:
    assert exif_date(jpeg("2021:06:01 10:20:30")) == (TS(2021, 6, 1, 10, 20, 30), None)
    assert exif_date(jpeg("2021:06:01 10:20:30", "+05:30")) == (TS(2021, 6, 1, 4, 50, 30), 330)
    assert exif_date(jpeg("0000:00:00 00:00:00", digitized="2020:01:01 00:00:00"))[0] == TS(2020, 1, 1)  # fmt: skip
    assert exif_date(jpeg("1970:01:01 00:00:00")) is None
    assert exif_date(jpeg()) is None
    assert exif_date(b"\xff\xd8\xff not really") is None
    cases = {
        "IMG_20230514_123456.jpg": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "PXL_20230514_123456789.jpg": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "VID_20230514_123456.mp4": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "Screenshot_2023-05-14-12-34-56.png": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "Screenshot 2023-05-14 at 12.34.56.png": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "2023-05-14 12.34.56.jpg": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "20230514_123456.jpg": (TS(2023, 5, 14, 12, 34, 56), "filename"),
        "IMG-20230514-WA0001.jpg": (TS(2023, 5, 14), "filename_day"),
    }
    for name, want in cases.items():
        assert filename_date(name) == want, name
    for bad in ("IMG_19800514_123456.jpg", "IMG_20231399_123456.jpg", "IMG_29990101_000000.jpg",
                "photo.jpg", "IMG_1234.jpg"):  # fmt: skip
        assert filename_date(bad) is None, bad


def _folder(tmp: Path) -> Path:
    d = tmp / "pics"
    d.mkdir()
    (d / "a_exif.jpg").write_bytes(jpeg("2021:06:01 10:20:30", "+05:30"))
    (d / "IMG_20230514_123456.jpg").write_bytes(jpeg())
    (d / "plain.jpg").write_bytes(jpeg())
    (d / "broken.jpg").write_bytes(b"\xff\xd8\xff\xe1 truncated")
    (d / "clip.mp4").write_bytes(b"\x00" * 10)
    for f in d.iterdir():
        os.utime(f, (OLD, OLD))
    return d


def _zip(tmp: Path) -> Path:
    z = tmp / "takeout-001.zip"
    y = "Takeout/Google Photos/Photos from 2024"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr(f"{y}/side.jpg", jpeg("2001:01:01 00:00:00"))
        w.writestr(f"{y}/side.jpg.json", json.dumps(
            {"title": "side.jpg", "photoTakenTime": {"timestamp": "1700000000"}}))  # fmt: skip
        w.writestr(f"{y}/nosidecar_exif.jpg", jpeg("2019:02:03 04:05:06"))
        w.writestr(f"{y}/VID_20220101_101010.mp4", b"\x00")
        w.writestr(f"{y}/nothing.jpg", jpeg())
    return z


def test_run_folder_and_takeout(tmp_path: Path) -> None:
    d, z = _folder(tmp_path), _zip(tmp_path)
    before = {f: (f.read_bytes(), f.stat().st_mtime) for f in [*d.iterdir(), z]}
    con = store.connect(tmp_path / "s.db")
    store.import_records(con, scan_folder(d), source="folder", root=str(d))
    store.import_records(con, scan_takeout([z]), source="takeout", root=str(tmp_path))
    c = run_dates(con, batch_size=2)
    r = rows(con)
    assert r["a_exif.jpg"][:3] == (TS(2021, 6, 1, 4, 50, 30), "exif", 330)
    assert r["IMG_20230514_123456.jpg"][:3] == (TS(2023, 5, 14, 12, 34, 56), "filename", None)
    assert r["plain.jpg"][:2] == (OLD, "file")
    assert r["broken.jpg"][:2] == (OLD, "file")  # unreadable EXIF falls through, no crash
    assert r["clip.mp4"][:2] == (OLD, "file")  # videos: no EXIF in this task
    assert r["side.jpg"][:3] == (1700000000.0, "takeout", None)  # never overwritten by EXIF
    assert r["nosidecar_exif.jpg"][:2] == (TS(2019, 2, 3, 4, 5, 6), "exif")
    assert r["VID_20220101_101010.mp4"][:2] == (TS(2022, 1, 1, 10, 10, 10), "filename")
    assert r["nothing.jpg"][:2] == (None, "")  # Takeout zip time = export time: not used
    assert all(v[3] for v in r.values())
    assert c["missing"] == 1 and c["done"] == 9 and c["todo"] == 9
    s = store.stats(con)
    assert (s["date_takeout"], s["date_exif"], s["date_filename"], s["date_file"],
            s["date_missing"], s["dates_todo"]) == (1, 2, 2, 3, 1, 0)  # fmt: skip
    assert run_dates(con)["todo"] == 0  # finished: nothing to redo
    assert {f: (f.read_bytes(), f.stat().st_mtime) for f in before} == before


def test_resume_after_stop_and_reimport(tmp_path: Path) -> None:
    d = _folder(tmp_path)
    con = store.connect(tmp_path / "s.db")
    store.import_records(con, scan_folder(d), source="folder", root=str(d))

    def stop(c: dict[str, int]) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_dates(con, batch_size=2, on_progress=stop)
    assert sum(1 for v in rows(con).values() if v[3]) == 2  # first batch kept
    assert run_dates(con)["todo"] == 3

    (d / "plain.jpg").write_bytes(jpeg("2018:08:08 08:08:08"))  # file changed by the user
    store.import_records(con, scan_folder(d), source="folder", root=str(d))
    assert rows(con)["plain.jpg"][3] is None
    run_dates(con)
    assert rows(con)["plain.jpg"][:2] == (TS(2018, 8, 8, 8, 8, 8), "exif")


def test_heic_exif() -> None:
    ex = Image.Exif()
    ifd = ex.get_ifd(0x8769)
    ifd[36867], ifd[36881] = "2022:03:04 05:06:07", "-04:00"
    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, "HEIF", exif=ex)
    assert exif_date(buf.getvalue()) == (TS(2022, 3, 4, 9, 6, 7), -240)
