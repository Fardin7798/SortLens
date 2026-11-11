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
    taken_at_source: str = (
        ""  # "takeout" | "takeout_live"; later steps add "exif" | "filename" | "file"
    )
    lat: float | None = None  # best location: Google's geoData, else the camera's geoDataExif
    lon: float | None = None
    location_source: str = ""  # "google" | "camera" | ""
    gps_lat: float | None = None  # camera GPS exactly as geoDataExif has it (None when 0,0/missing)
    gps_lon: float | None = None
    title: str = ""
    description: str = ""
    people: list[str] = field(default_factory=list)
    favorited: bool = False
    # Takeout-only facts (empty/False/None for folders)
    uploaded_at: float | None = None  # creationTime: upload time, NOT the capture date
    archived: bool = False
    trashed: bool = False  # flag in the sidecar, or file sits in the Takeout trash folder
    image_views: int | None = None
    origin: str = ""  # googlePhotosOrigin key as Google writes it, e.g. "mobileUpload"
    device_type: str = ""  # googlePhotosOrigin.mobileUpload.deviceType, e.g. "ANDROID_PHONE"
    partner_shared: bool = False  # googlePhotosOrigin.fromPartnerSharing
    special_folder: str = ""  # "trash" | "failed_videos" | "untitled_album" | ""
    album_copy_of: str = ""  # rel_path of the same photo in a "Photos from YYYY" folder
    live_photo_of: str = ""  # for a live/motion video half: rel_path of its still photo
    sidecar_json: str = ""  # the matched sidecar exactly as read, so nothing is lost


@dataclass
class AlbumRecord:
    """One Takeout album folder, from its metadata.json (any language)."""

    root: str
    folder: str  # album folder rel_path, "/"-separated
    title: str = ""
    description: str = ""
    access: str = ""
    date: float | None = None
    lat: float | None = None
    lon: float | None = None
