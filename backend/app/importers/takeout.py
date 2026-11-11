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

from app.importers.base import MediaRecord, media_kind

SUPPLEMENTAL = "supplemental-metadata"
YEAR_FOLDER = re.compile(
    r"^(Photos from|Fotos del|Fotos von|Foto da|Foto's van|Photos de) \d{4}$", re.IGNORECASE
)
COUNTER = re.compile(r"^(?P<base>.*?)\((?P<n>\d+)\)$")
EDITED = re.compile(r"-(edited|EDIT|bearbeitet|modifié|editado|modificato)$", re.IGNORECASE)


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


def _apply_sidecar(rec: MediaRecord, data: dict[str, Any]) -> None:
    ptt = data.get("photoTakenTime") or {}
    ts = ptt.get("timestamp") if isinstance(ptt, dict) else None
    if ts not in (None, "", "0"):
        rec.taken_at = float(ts)
        rec.taken_at_source = "takeout"
    for key in ("geoData", "geoDataExif"):
        g = data.get(key) or {}
        lat, lon = g.get("latitude"), g.get("longitude")
        if isinstance(lat, int | float) and isinstance(lon, int | float) and (lat, lon) != (0, 0):
            rec.lat, rec.lon = float(lat), float(lon)
            break
    rec.title = str(data.get("title") or "")
    rec.description = str(data.get("description") or "")
    rec.people = [str(p["name"]) for p in data.get("people") or [] if p.get("name")]
    rec.favorited = bool(data.get("favorited"))


def scan_takeout(paths: list[Path]) -> Iterator[MediaRecord]:
    """`paths`: zip parts of one export, or a single extracted folder."""
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

    def load(e: _Entry) -> dict[str, Any] | None:
        k = e.container + "|" + e.rel_path
        if k not in parsed:
            try:
                d = json.loads(_read(e, roots).decode("utf-8"))
                parsed[k] = d if isinstance(d, dict) and "photoTakenTime" in d else None
            except (ValueError, OSError, KeyError):
                parsed[k] = None  # broken or album metadata.json: ignore
        return parsed[k]

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
        album = "" if YEAR_FOLDER.match(pp.parent.name) else pp.parent.name
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
        )
        sc = find_sidecar(folder, pp.name)
        if sc is not None:
            data = load(sc)
            if data is not None:
                rec.sidecar = sc.rel_path
                _apply_sidecar(rec, data)
        yield rec
