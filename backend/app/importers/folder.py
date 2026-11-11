"""Read a plain laptop folder (recursively). Read-only: only stat() is called here."""

import os
from collections.abc import Iterator
from pathlib import Path

from app.importers.base import MediaRecord, media_kind


def scan_folder(root: Path) -> Iterator[MediaRecord]:
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            kind = media_kind(fn)
            if kind is None:
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue  # unreadable file: skip, never fail the whole scan
            yield MediaRecord(
                source="folder",
                root=str(root),
                container="",
                rel_path=p.relative_to(root).as_posix(),
                name=fn,
                kind=kind,
                size=st.st_size,
                mtime=st.st_mtime,
            )
