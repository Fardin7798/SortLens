"""Read a Google Takeout (Google Photos) export: one or more zip parts, or an extracted folder.

Read-only. Zips are opened with zipfile in read mode; nothing is extracted to disk.
See docs/TAKEOUT.md for the format quirks handled here.
"""

import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.importers.base import AlbumRecord, MediaRecord, media_kind

SUPPLEMENTAL = "supplemental-metadata"
YEAR_FOLDER = re.compile(
    r"^(Photos from|Fotos del|Fotos von|Foto da|Foto's van|Photos de) \d{4}$", re.IGNORECASE
)
COUNTER = re.compile(r"^(?P<base>.*?)\((?P<n>\d+)\)$")
EDITED = re.compile(r"-(edited|EDIT|bearbeitet|modifié|editado|modificato)$", re.IGNORECASE)
# Special folders, matched by name in the export's language (lowercased).
TRASH_NAMES = {
    "trash", "bin", "corbeille", "papierkorb", "papelera", "cestino", "prullenbak", "lixeira",
    "lixo", "kosz", "корзина",
}  # fmt: skip
FAILED_VIDEOS = re.compile(r"^failed videos$", re.IGNORECASE)
UNTITLED = re.compile(
    r"^(untitled|sin título|sans titre|ohne titel|senza titolo|zonder titel|sem título)"
    r"(\(\d+\))?$",
    re.IGNORECASE,
)


def special_folder(folder_name: str) -> str:
    if folder_name.lower() in TRASH_NAMES:
        return "trash"
    if FAILED_VIDEOS.match(folder_name):
        return "failed_videos"
    if UNTITLED.match(folder_name):
        return "untitled_album"
    return ""


@dataclass
class _Entry:
    container: str  # zip path or ""
    rel_path: str  # "/"-separated
    size: int
    mtime: float


def _sidecar_key(json_name: str) -> tuple[str, int]:
    """'IMG.jpg.supplemental-metad(1).json' -> ('IMG.jpg', 1). Name part may still be cut."""
    base = json_name[: -len(".json")]
    n = 0
    m = COUNTER.match(base)
    if m:
        base, n = m.group("base"), int(m.group("n"))
    if "." in base:
        head, last = base.rsplit(".", 1)
        if last and SUPPLEMENTAL.startswith(last) and media_kind(base) is None:
            base = head
    m = COUNTER.match(base)  # older style: 'IMG.jpg(1)' after stripping the suffix
    if m and n == 0:
        base, n = m.group("base"), int(m.group("n"))
    return base, n


def _media_key(name: str) -> tuple[str, int, bool]:
    """'IMG(1).jpg' -> ('IMG.jpg', 1, False); 'IMG-edited.jpg' -> ('IMG.jpg', 0, True)."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    edited = False
    m = EDITED.search(stem)
    if m:
        stem, edited = stem[: m.start()], True
    n = 0
    m2 = COUNTER.match(stem)
    if m2:
        stem, n = m2.group("base"), int(m2.group("n"))
    return (f"{stem}.{ext}" if ext else stem), n, edited


def _list_entries(paths: list[Path]) -> list[_Entry]:
    out: list[_Entry] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    st = f.stat()
                    out.append(_Entry("", f.relative_to(p).as_posix(), st.st_size, st.st_mtime))
        elif zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    ts = datetime(*info.date_time).timestamp()
                    out.append(_Entry(str(p.resolve()), info.filename, info.file_size, ts))
    return out


def _read(entry: _Entry, roots: dict[str, Path]) -> bytes:
    if entry.container:
        with zipfile.ZipFile(entry.container) as z:
            return z.read(entry.rel_path)
    return (roots[""] / entry.rel_path).read_bytes()


def _ts(v: Any) -> float | None:
    t = v.get("timestamp") if isinstance(v, dict) else None
    try:
        f = float(t) if t not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return f if f else None  # 0 means "not set"


def _geo(v: Any) -> tuple[float, float] | None:
    if not isinstance(v, dict):
        return None
    lat, lon = v.get("latitude"), v.get("longitude")
    if isinstance(lat, int | float) and isinstance(lon, int | float) and (lat, lon) != (0, 0):
        return float(lat), float(lon)
    return None  # 0,0 means no location


def _apply_sidecar(rec: MediaRecord, data: dict[str, Any]) -> None:
    taken = _ts(data.get("photoTakenTime"))
    if taken is not None:
        rec.taken_at, rec.taken_at_source = taken, "takeout"
    rec.uploaded_at = _ts(data.get("creationTime"))
    google, camera = _geo(data.get("geoData")), _geo(data.get("geoDataExif"))
    if camera:
        rec.gps_lat, rec.gps_lon = camera
    if google:
        (rec.lat, rec.lon), rec.location_source = google, "google"
    elif camera:
        (rec.lat, rec.lon), rec.location_source = camera, "camera"
    rec.title = str(data.get("title") or "")
    rec.description = str(data.get("description") or "")
    rec.people = [
        str(p["name"]) for p in data.get("people") or [] if isinstance(p, dict) and p.get("name")
    ]
    rec.favorited = bool(data.get("favorited"))
    rec.archived = bool(data.get("archived"))
    rec.trashed = rec.trashed or bool(data.get("trashed"))
    views = str(data.get("imageViews", ""))
    rec.image_views = int(views) if views.isdigit() else None
    origin = data.get("googlePhotosOrigin")
    if isinstance(origin, dict) and origin:
        rec.origin = next(iter(origin))
        rec.partner_shared = "fromPartnerSharing" in origin
        mobile = origin.get("mobileUpload")
        if isinstance(mobile, dict):
            rec.device_type = str(mobile.get("deviceType") or "")
    rec.sidecar_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _album_from(root: str, folder: str, data: dict[str, Any]) -> AlbumRecord:
    d = data.get("albumData") if isinstance(data.get("albumData"), dict) else data
    assert isinstance(d, dict)
    geo = _geo(d.get("geoData"))
    return AlbumRecord(
        root=root,
        folder=folder,
        title=str(d.get("title") or ""),
        description=str(d.get("description") or ""),
        access=str(d.get("access") or ""),
        date=_ts(d.get("date")),
        lat=geo[0] if geo else None,
        lon=geo[1] if geo else None,
    )


def scan_takeout(
    paths: list[Path], albums: list[AlbumRecord] | None = None
) -> Iterator[MediaRecord]:
    """`paths`: zip parts of one export, or a single extracted folder.
    Album metadata.json files found on the way are appended to `albums` when given."""
    paths = [p.resolve() for p in paths]
    root_label = str(paths[0].parent if paths[0].is_file() else paths[0])
    roots = {"": paths[0]} if paths[0].is_dir() else {}
    entries = _list_entries(paths)

    # Index sidecars per folder across ALL zip parts (a photo and its JSON can sit in different parts).
    by_key: dict[tuple[str, str, int], _Entry] = {}
    jsons: dict[str, list[_Entry]] = {}
    for e in entries:
        pp = PurePosixPath(e.rel_path)
        if pp.suffix.lower() != ".json":
            continue
        folder = str(pp.parent)
        jsons.setdefault(folder, []).append(e)
        base, n = _sidecar_key(pp.name)
        by_key[(folder, base, n)] = e

    parsed: dict[str, dict[str, Any] | None] = {}

    def load_any(e: _Entry) -> dict[str, Any] | None:
        k = e.container + "|" + e.rel_path
        if k not in parsed:
            try:
                d = json.loads(_read(e, roots).decode("utf-8"))
                parsed[k] = d if isinstance(d, dict) else None
            except (ValueError, OSError, KeyError):
                parsed[k] = None  # broken JSON: ignore, never guess
        return parsed[k]

    def load(e: _Entry) -> dict[str, Any] | None:
        """Only photo/video sidecars (they always carry photoTakenTime)."""
        d = load_any(e)
        return d if d is not None and "photoTakenTime" in d else None

    # Album metadata.json (name differs per language): a JSON whose base is not a media name
    # and that has no photoTakenTime.
    if albums is not None:
        for folder, items in jsons.items():
            for e in items:
                base, _ = _sidecar_key(PurePosixPath(e.rel_path).name)
                if media_kind(base) is not None:
                    continue
                d = load_any(e)
                if d is not None and "photoTakenTime" not in d:
                    albums.append(_album_from(root_label, folder, d))
                    break

    # Same photo in a "Photos from YYYY" folder, by name + size: album folders hold copies.
    year_copy: dict[tuple[str, int], str] = {}
    photos_by_stem: dict[tuple[str, str], str] = {}
    for e in entries:
        pp = PurePosixPath(e.rel_path)
        kind = media_kind(pp.name)
        if kind is None:
            continue
        if YEAR_FOLDER.match(pp.parent.name):
            year_copy.setdefault((pp.name, e.size), e.rel_path)
        if kind == "photo":
            photos_by_stem.setdefault((str(pp.parent), pp.stem.lower()), pp.name)

    def find_sidecar(folder: str, name: str) -> _Entry | None:
        full, n, _ = _media_key(name)
        hit = by_key.get((folder, full, n))
        if hit:
            return hit
        # Names cut at ~51 chars: the sidecar base is a prefix of the media name.
        cands = [
            e
            for (f, b, k), e in by_key.items()
            if f == folder and k == n and len(b) >= 20 and full.startswith(b)
        ]
        if len(cands) == 1:
            return cands[0]
        # Last resort: the JSON 'title' holds the full original name.
        for e in jsons.get(folder, []):
            d = load(e)
            if d and d.get("title") == full:
                return e
        return None

    for e in entries:
        pp = PurePosixPath(e.rel_path)
        kind = media_kind(pp.name)
        if kind is None:
            continue
        folder = str(pp.parent)
        _, _, edited = _media_key(pp.name)
        special = special_folder(pp.parent.name)
        in_year = bool(YEAR_FOLDER.match(pp.parent.name))
        album = "" if in_year or special in ("trash", "failed_videos") else pp.parent.name
        rec = MediaRecord(
            source="takeout",
            root=root_label,
            container=e.container,
            rel_path=e.rel_path,
            name=pp.name,
            kind=kind,
            size=e.size,
            mtime=e.mtime,
            album=album,
            is_edited=edited,
            special_folder=special,
            trashed=special == "trash",
        )
        if not in_year:
            rec.album_copy_of = year_copy.get((pp.name, e.size), "")
        sc = find_sidecar(folder, pp.name)
        if sc is not None:
            data = load(sc)
            if data is not None:
                rec.sidecar = sc.rel_path
                _apply_sidecar(rec, data)
        if kind == "video":
            still = photos_by_stem.get((folder, pp.stem.lower()))
            if still:
                rec.live_photo_of = f"{folder}/{still}"
                if rec.taken_at is None:  # the video half usually has no sidecar
                    ssc = find_sidecar(folder, still)
                    sdata = load(ssc) if ssc else None
                    taken = _ts(sdata.get("photoTakenTime")) if sdata else None
                    if taken is not None:
                        rec.taken_at, rec.taken_at_source = taken, "takeout_live"
        yield rec
