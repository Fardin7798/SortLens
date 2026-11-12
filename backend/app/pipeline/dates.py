"""Best "taken at" date for every media row, with where it came from.

Priority, first hit wins:
  takeout / takeout_live  photoTakenTime from the sidecar (set by the importer, never changed here)
  exif                    photos: DateTimeOriginal, else DateTimeDigitized (+ OffsetTime* if present)
  filename / filename_day dated file names (IMG_20230514_123456, Screenshot_2023-05-14-..., WhatsApp)
  file                    file modified time; plain folders only (see below)

Times without a stated zone are stored as if UTC with taken_at_offset = NULL ("local time, zone
unknown"). No zone is guessed. For Takeout files the file/zip time is when Google built the export,
not when the photo was taken, so it is never used: such rows stay without a date (missing stays
missing). Files are only read. Resumable: rows with dates_done_at set are skipped.
"""

import io
import logging
import re
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

from PIL import Image

from app.core.media_io import MediaReader

log = logging.getLogger(__name__)

MIN_YEAR = 1990
SOURCES = ("takeout", "takeout_live", "exif", "filename", "filename_day", "file")

_EXIF_IFD = 0x8769
_ORIGINAL, _DIGITIZED = 36867, 36868
_OFFSET_ORIGINAL, _OFFSET_DIGITIZED = 36881, 36882

_heif_ready = False


def _heif() -> None:
    global _heif_ready
    if not _heif_ready:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:  # pragma: no cover - dependency is required, but stay safe
            pass
        _heif_ready = True


def _valid(dt: datetime, now: float) -> bool:
    return MIN_YEAR <= dt.year and dt.timestamp() <= now + 86400


def _offset_minutes(text: object) -> int | None:
    m = re.fullmatch(r"\s*([+-])(\d{2}):?(\d{2})\s*", str(text or ""))
    if not m:
        return None
    mins = int(m[2]) * 60 + int(m[3])
    return -mins if m[1] == "-" else mins


def exif_date(data: bytes, now: float | None = None) -> tuple[float, int | None] | None:
    """(epoch seconds, offset minutes or None) from EXIF, or None."""
    now = time.time() if now is None else now
    _heif()
    try:
        with Image.open(io.BytesIO(data)) as im:
            ifd = im.getexif().get_ifd(_EXIF_IFD)
    except Exception as e:  # broken or unknown file: fall through to the next source
        log.debug("no exif: %s", e)
        return None
    for tag, off_tag in ((_ORIGINAL, _OFFSET_ORIGINAL), (_DIGITIZED, _OFFSET_DIGITIZED)):
        raw = str(ifd.get(tag) or "").strip().rstrip("\x00")
        try:
            dt = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue  # empty, "0000:00:00 00:00:00", or garbage
        off = _offset_minutes(ifd.get(off_tag))
        zone = UTC if off is None else timezone(timedelta(minutes=off))
        aware = dt.replace(tzinfo=zone)
        if _valid(aware, now):
            return aware.timestamp(), off
    return None


_FULL = [
    # IMG_20230514_123456, VID_, PXL_20230514_123456789, 20230514_123456, Screenshot_20230514-123456
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})\d{0,3}(?!\d)"),
    # Screenshot_2023-05-14-12-34-56, 2023-05-14 12.34.56, Screenshot 2023-05-14 at 12.34.56
    re.compile(
        r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:[ _-]|\sat\s)(\d{2})[.:-](\d{2})[.:-](\d{2})(?!\d)"
    ),
]
_DAY = [re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})-WA\d+", re.IGNORECASE)]  # WhatsApp: day only


def filename_date(name: str, now: float | None = None) -> tuple[float, str] | None:
    """(epoch seconds as if UTC, "filename" | "filename_day") from a dated file name, or None."""
    now = time.time() if now is None else now
    for pats, src in ((_FULL, "filename"), (_DAY, "filename_day")):
        for p in pats:
            for m in p.finditer(name):
                y, mo, d, h, mi, sec = ([int(x) for x in m.groups()] + [0, 0, 0])[:6]
                try:
                    dt = datetime(y, mo, d, h, mi, sec, tzinfo=UTC)
                except ValueError:
                    continue
                if _valid(dt, now):
                    return dt.timestamp(), src
    return None


def run_dates(
    con: sqlite3.Connection,
    *,
    reader: MediaReader | None = None,
    batch_size: int = 50,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Fill taken_at / taken_at_source / taken_at_offset for rows not done yet. Returns counts."""
    now = time.time()
    rows = con.execute(
        "SELECT id, source, root, container, rel_path, name, kind, mtime, taken_at, "
        "taken_at_source FROM media WHERE dates_done_at IS NULL ORDER BY id"
    ).fetchall()
    counts = {"todo": len(rows), "done": 0, "read_errors": 0, "missing": 0}
    counts.update(dict.fromkeys(SOURCES, 0))
    own = reader is None
    rd = reader or MediaReader()
    try:
        for i, (mid, source, root, container, rel, name, kind, mtime, taken, tsrc) in enumerate(
            rows, 1
        ):
            new: tuple[float | None, str, int | None]
            if taken is not None and tsrc in ("takeout", "takeout_live"):
                new = (taken, tsrc, None)
            else:
                new = (None, "", None)
                if kind == "photo":
                    try:
                        got = exif_date(rd.read(root, container, rel), now)
                    except Exception as e:  # unreadable file: log, fall through
                        counts["read_errors"] += 1
                        log.warning("could not read %s: %s", rel, e)
                        got = None
                    if got:
                        new = (got[0], "exif", got[1])
                if new[0] is None and (fn := filename_date(name, now)):
                    new = (fn[0], fn[1], None)
                if new[0] is None and source != "takeout" and mtime and mtime >= 0:
                    dt = datetime.fromtimestamp(mtime, UTC)
                    if _valid(dt, now):
                        new = (mtime, "file", None)
            con.execute(
                "UPDATE media SET taken_at=?, taken_at_source=?, taken_at_offset=?, "
                "dates_done_at=? WHERE id=?",
                (*new, time.time(), mid),
            )
            counts["done"] += 1
            counts[new[1] or "missing"] += 1
            if i % batch_size == 0:
                con.commit()
                if on_progress:
                    on_progress(dict(counts))
        con.commit()
    finally:
        if own:
            rd.close()
    if on_progress:
        on_progress(dict(counts))
    return counts
