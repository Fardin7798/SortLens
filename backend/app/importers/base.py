"""Shared record type for every importer. Importers only READ files."""

from dataclasses import dataclass, field

PHOTO_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp",
    ".tif", ".tiff", ".dng", ".cr2", ".nef", ".arw", ".raf", ".orf", ".rw2",
}  # fmt: skip
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm", ".mts"}
MEDIA_EXTS = PHOTO_EXTS | VIDEO_EXTS


def media_kind(name: str) -> str | None:
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    return None


@dataclass
class MediaRecord:
    """One photo or video. `container` is the zip path when the file sits inside a zip."""

    source: str  # "takeout" | "folder"
    root: str  # the folder or Takeout export the user pointed at
    container: str  # zip file path, or "" for plain files
    rel_path: str  # path inside root/container, always with "/"
    name: str
    kind: str  # "photo" | "video"
    size: int
    mtime: float  # file modified time (epoch seconds); zip entry time for zips
    album: str = ""  # Takeout album folder name ("" for year folders / plain folders)
    is_edited: bool = False  # Takeout "-edited" copy
    sidecar: str = ""  # rel_path of the matched Takeout JSON, "" when none
    taken_at: float | None = None  # epoch seconds UTC, only when a source gives it
    taken_at_source: str = ""  # "takeout" here; later steps add "exif" | "filename" | "file"
    lat: float | None = None
    lon: float | None = None
    title: str = ""
    description: str = ""
    people: list[str] = field(default_factory=list)
    favorited: bool = False
