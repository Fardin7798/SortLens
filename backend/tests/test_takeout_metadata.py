"""Every Takeout fact the importer keeps: flags, origin, camera GPS, special folders, albums,
album copies and live-photo pairs. Data is generated here; no real photos are used."""

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from app.cli import main
from app.db import store
from app.importers.base import AlbumRecord
from app.importers.takeout import scan_takeout, special_folder

GP = "Takeout/Google Photos"


def _j(**d: object) -> bytes:
    return json.dumps(d).encode()


def _make(tmp: Path) -> Path:
    z = tmp / "takeout-001.zip"
    y = f"{GP}/Photos from 2023"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr(f"{y}/A.jpg", b"a")
        w.writestr(
            f"{y}/A.jpg.supplemental-metadata.json",
            _j(
                title="A.jpg",
                photoTakenTime={"timestamp": "1690000000"},
                creationTime={"timestamp": "1690500000"},
                geoData={"latitude": 0.0, "longitude": 0.0},
                geoDataExif={"latitude": 21.1458, "longitude": 79.0882},
                imageViews="12",
                archived=True,
                googlePhotosOrigin={"mobileUpload": {"deviceType": "ANDROID_PHONE"}},
            ),
        )
        w.writestr(f"{y}/B.jpg", b"b")
        w.writestr(
            f"{y}/B.jpg.json",
            _j(
                title="B.jpg",
                photoTakenTime={"timestamp": "1690000100"},
                geoData={"latitude": 19.07, "longitude": 72.87},
                geoDataExif={"latitude": 19.0, "longitude": 72.0},
                googlePhotosOrigin={"fromPartnerSharing": {}},
                people=[{"name": "Fardin"}, {"name": "Ashhal"}],
            ),
        )
        # Live photo: still + video half without its own sidecar
        w.writestr(f"{y}/IMG_7.HEIC", b"still")
        w.writestr(
            f"{y}/IMG_7.HEIC.json",
            _j(title="IMG_7.HEIC", photoTakenTime={"timestamp": "1690000200"}),
        )
        w.writestr(f"{y}/IMG_7.MOV", b"motion")
        # Album: copy of A.jpg + metadata.json (new style) and an old-style albumData album
        w.writestr(f"{GP}/Nagpur Trip/A.jpg", b"a")
        w.writestr(
            f"{GP}/Nagpur Trip/A.jpg.json",
            _j(title="A.jpg", photoTakenTime={"timestamp": "1690000000"}),
        )
        w.writestr(
            f"{GP}/Nagpur Trip/metadata.json",
            _j(title="Nagpur Trip", description="Dec", access="protected",
               date={"timestamp": "1690000000"}),
        )  # fmt: skip
        w.writestr(f"{GP}/Old/C.png", b"c")
        w.writestr(f"{GP}/Old/métadonnées.json", _j(albumData={"title": "Old album"}))
        w.writestr(f"{GP}/Untitled(2)/D.jpg", b"d")
        # Trash folder (flag missing in sidecar) and a sidecar trashed flag
        w.writestr(f"{GP}/Trash/E.jpg", b"e")
        w.writestr(f"{GP}/Trash/E.jpg.json", _j(title="E.jpg", photoTakenTime={"timestamp": "1"}))
        w.writestr(f"{y}/F.jpg", b"f")
        w.writestr(
            f"{y}/F.jpg.json",
            _j(title="F.jpg", photoTakenTime={"timestamp": "1690000300"}, trashed=True),
        )
        w.writestr(f"{GP}/Failed Videos/G.mp4", b"g")
        w.writestr(f"{GP}/Broken/H.jpg", b"h")
        w.writestr(f"{GP}/Broken/H.jpg.json", b"{not json")
    return z


def _sha(p: Path) -> tuple[str, float]:
    return hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime


def test_special_folder_names() -> None:
    assert special_folder("Trash") == "trash"
    assert special_folder("Corbeille") == "trash"
    assert special_folder("Failed Videos") == "failed_videos"
    assert special_folder("Untitled(3)") == "untitled_album"
    assert special_folder("Goa 2022") == ""


def test_all_takeout_facts(tmp_path: Path) -> None:
    z = _make(tmp_path)
    before = _sha(z)
    albums: list[AlbumRecord] = []
    recs = {r.rel_path.split("/", 2)[2]: r for r in scan_takeout([z], albums)}

    a = recs["Photos from 2023/A.jpg"]
    assert a.uploaded_at == 1690500000 and a.taken_at == 1690000000
    assert (a.lat, a.lon, a.location_source) == (21.1458, 79.0882, "camera")
    assert (a.gps_lat, a.gps_lon) == (21.1458, 79.0882)
    assert a.archived and not a.trashed and a.image_views == 12
    assert (a.origin, a.device_type, a.partner_shared) == ("mobileUpload", "ANDROID_PHONE", False)
    assert json.loads(a.sidecar_json)["imageViews"] == "12"  # raw sidecar kept

    b = recs["Photos from 2023/B.jpg"]
    assert (b.lat, b.lon, b.location_source) == (19.07, 72.87, "google")
    assert (b.gps_lat, b.gps_lon) == (19.0, 72.0)
    assert b.partner_shared and b.origin == "fromPartnerSharing"
    assert b.people == ["Fardin", "Ashhal"] and b.image_views is None

    mov = recs["Photos from 2023/IMG_7.MOV"]
    assert mov.live_photo_of.endswith("Photos from 2023/IMG_7.HEIC")
    assert (mov.taken_at, mov.taken_at_source) == (1690000200, "takeout_live")
    assert recs["Photos from 2023/IMG_7.HEIC"].live_photo_of == ""

    copy = recs["Nagpur Trip/A.jpg"]
    assert copy.album == "Nagpur Trip" and copy.album_copy_of.endswith("Photos from 2023/A.jpg")
    assert recs["Photos from 2023/A.jpg"].album_copy_of == ""
    assert recs["Old/C.png"].album_copy_of == ""  # no year copy: stays empty

    d = recs["Untitled(2)/D.jpg"]
    assert d.special_folder == "untitled_album" and d.album == "Untitled(2)"
    e = recs["Trash/E.jpg"]
    assert e.trashed and e.special_folder == "trash" and e.album == ""
    assert recs["Photos from 2023/F.jpg"].trashed
    g = recs["Failed Videos/G.mp4"]
    assert g.special_folder == "failed_videos" and g.album == "" and g.taken_at is None
    h = recs["Broken/H.jpg"]
    assert h.sidecar == "" and h.taken_at is None  # broken JSON: missing stays missing

    by_folder = {al.folder.split("/", 2)[2]: al for al in albums}
    assert set(by_folder) == {"Nagpur Trip", "Old"}
    n = by_folder["Nagpur Trip"]
    assert (n.title, n.description, n.access, n.date) == ("Nagpur Trip", "Dec", "protected",
                                                         1690000000)  # fmt: skip
    assert by_folder["Old"].title == "Old album"

    assert _sha(z) == before  # read-only


def test_store_cli_people_and_stats(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    z = _make(tmp_path)
    assert main(["import-takeout", str(z)]) == 0
    assert '"albums": 2' in capsys.readouterr().out
    assert main(["stats"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["archived"] == 1 and s["trashed"] == 2 and s["partner_shared"] == 1
    assert s["failed_videos"] == 1 and s["album_copies"] == 1 and s["live_videos"] == 1
    assert s["location_google"] == 1 and s["location_camera"] == 1
    assert s["with_people"] == 1 and s["people_names"] == 2 and s["albums"] == 2
    assert main(["people"]) == 0
    out = capsys.readouterr().out
    assert "Fardin" in out and "Ashhal" in out


def test_old_database_is_upgraded_and_reread(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    old = sqlite3.connect(db)
    old.executescript(store.SCHEMA.replace("CREATE TABLE IF NOT EXISTS albums", "CREATE TABLE x"))
    old.execute(
        "INSERT INTO media (source, root, rel_path, name, kind, size, mtime, imported_at) "
        "VALUES ('takeout', 'r', 'p', 'n', 'photo', 1, 1.0, 0)"
    )
    old.commit()
    old.close()
    con = store.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(media)")}
    assert set(store.ADDED_COLUMNS) <= cols
    assert con.execute("SELECT importer_version FROM media").fetchone()[0] == 1

    z = _make(tmp_path)
    first = store.import_records(con, scan_takeout([z]), source="takeout", root="r")
    con.execute("UPDATE media SET importer_version=1")  # pretend rows came from v0.1
    con.commit()
    again = store.import_records(con, scan_takeout([z]), source="takeout", root="r")
    assert again["updated"] == first["added"] and again["unchanged"] == 0
    third = store.import_records(con, scan_takeout([z]), source="takeout", root="r")
    assert third["unchanged"] == first["added"]
