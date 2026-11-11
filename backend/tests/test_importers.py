import hashlib
import json
import zipfile
from pathlib import Path

from app.cli import main
from app.core.config import settings
from app.db import store
from app.importers.folder import scan_folder
from app.importers.takeout import _media_key, _sidecar_key, scan_takeout

GP = "Takeout/Google Photos"


def _sidecar(title: str, ts: int, lat: float = 0.0, lon: float = 0.0, **extra: object) -> bytes:
    d = {
        "title": title,
        "photoTakenTime": {"timestamp": str(ts)},
        "geoData": {"latitude": lat, "longitude": lon},
        **extra,
    }
    return json.dumps(d).encode()


def _fingerprint(paths: list[Path]) -> dict[str, tuple[str, float]]:
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime) for p in paths}


def test_sidecar_and_media_keys() -> None:
    assert _sidecar_key("IMG_1.jpg.json") == ("IMG_1.jpg", 0)
    assert _sidecar_key("IMG_1.jpg.supplemental-metadata.json") == ("IMG_1.jpg", 0)
    assert _sidecar_key("PXL_20230721_092530123.jpg.supplemental-metada.json") == (
        "PXL_20230721_092530123.jpg",
        0,
    )
    assert _sidecar_key("IMG_3479.JPG(1).json") == ("IMG_3479.JPG", 1)
    assert _sidecar_key("IMG_3479.JPG.supplemental-metadata(1).json") == ("IMG_3479.JPG", 1)
    assert _media_key("IMG_3479(1).JPG") == ("IMG_3479.JPG", 1, False)
    assert _media_key("IMG_6540-edited.jpg") == ("IMG_6540.jpg", 0, True)


def _make_export(tmp: Path) -> list[Path]:
    """Two zip parts; one photo's JSON sits in the other part, like real exports."""
    z1, z2 = tmp / "takeout-001.zip", tmp / "takeout-002.zip"
    with zipfile.ZipFile(z1, "w") as z:
        z.writestr(f"{GP}/Photos from 2020/IMG_1.jpg", b"one")
        z.writestr(
            f"{GP}/Photos from 2020/IMG_1.jpg.supplemental-metadata.json",
            _sidecar("IMG_1.jpg", 1592847796, 21.14, 79.08, people=[{"name": "Fardin"}]),
        )
        z.writestr(f"{GP}/Photos from 2020/IMG_1-edited.jpg", b"one-edited")
        z.writestr(f"{GP}/Photos from 2021/IMG_3479(1).JPG", b"dup-name")
        z.writestr(f"{GP}/Photos from 2021/notes.txt", b"not media")
    with zipfile.ZipFile(z2, "w") as z:
        z.writestr(
            f"{GP}/Photos from 2021/IMG_3479.JPG.supplemental-metadata(1).json",
            _sidecar("IMG_3479.JPG", 1610000000, favorited=True),
        )
        long = "Screenshot_20240311-183022_WhatsApp_Business.jpg"
        z.writestr(f"{GP}/Photos from 2024/{long}", b"shot")
        z.writestr(
            f"{GP}/Photos from 2024/Screenshot_20240311-183022_WhatsApp.json",
            _sidecar(long, 1710161422),
        )
        z.writestr(f"{GP}/Trip Goa/IMG_1.jpg", b"one")
        z.writestr(f"{GP}/Trip Goa/IMG_1.jpg.json", _sidecar("IMG_1.jpg", 1592847796))
        z.writestr(f"{GP}/Trip Goa/metadata.json", json.dumps({"title": "Trip Goa"}).encode())
        z.writestr(f"{GP}/Photos from 2019/no_json.png", b"x")
    return [z1, z2]


def test_takeout_zip_parts(tmp_path: Path) -> None:
    parts = _make_export(tmp_path)
    before = _fingerprint(parts)
    recs = {r.rel_path.split("/", 2)[2]: r for r in scan_takeout(parts)}

    assert len(recs) == 6  # notes.txt and json files are not media
    a = recs["Photos from 2020/IMG_1.jpg"]
    assert a.taken_at == 1592847796 and a.taken_at_source == "takeout"
    assert (a.lat, a.lon) == (21.14, 79.08) and a.people == ["Fardin"]
    e = recs["Photos from 2020/IMG_1-edited.jpg"]
    assert e.is_edited and e.taken_at == 1592847796  # shares the original's sidecar
    c = recs["Photos from 2021/IMG_3479(1).JPG"]
    assert c.taken_at == 1610000000 and c.favorited  # JSON came from the other zip part
    assert recs["Photos from 2024/Screenshot_20240311-183022_WhatsApp_Business.jpg"].sidecar
    g = recs["Trip Goa/IMG_1.jpg"]
    assert g.album == "Trip Goa" and g.lat is None  # 0,0 means no location
    n = recs["Photos from 2019/no_json.png"]
    assert n.taken_at is None and n.sidecar == ""  # missing stays missing

    assert _fingerprint(parts) == before  # read-only


def test_takeout_extracted_folder(tmp_path: Path) -> None:
    parts = _make_export(tmp_path)
    out = tmp_path / "extracted"
    for p in parts:
        with zipfile.ZipFile(p) as z:
            z.extractall(out)
    recs = list(scan_takeout([out]))
    assert len(recs) == 6
    assert sum(1 for r in recs if r.taken_at is not None) == 5


def test_folder_scan_read_only(tmp_path: Path) -> None:
    (tmp_path / "pics" / "sub").mkdir(parents=True)
    files = [tmp_path / "pics" / "a.JPG", tmp_path / "pics" / "sub" / "b.mp4"]
    for f in files:
        f.write_bytes(b"data")
    (tmp_path / "pics" / "readme.txt").write_text("x")
    before = _fingerprint(files)
    recs = list(scan_folder(tmp_path / "pics"))
    assert sorted(r.rel_path for r in recs) == ["a.JPG", "sub/b.mp4"]
    assert {r.kind for r in recs} == {"photo", "video"}
    assert _fingerprint(files) == before


def test_import_is_resumable(tmp_path: Path) -> None:
    parts = _make_export(tmp_path)
    con = store.connect(tmp_path / "t.db")
    first = store.import_records(con, scan_takeout(parts), source="takeout", root="x")
    assert first["added"] == 6
    again = store.import_records(con, scan_takeout(parts), source="takeout", root="x")
    assert again == {"seen": 6, "added": 0, "updated": 0, "unchanged": 6}
    s = store.stats(con)
    assert s["total"] == 6 and s["with_date"] == 5 and s["takeout_without_sidecar"] == 1


def test_cli_import_and_stats(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    parts = _make_export(tmp_path)
    assert main(["import-takeout", *map(str, parts)]) == 0
    assert main(["stats"]) == 0
    out = capsys.readouterr().out
    assert '"total": 6' in out
    assert settings.db_path.exists()
    assert main(["import-folder", str(tmp_path / "nope")]) == 2
