"""Read-only access to a media file's bytes, wherever the importer found it."""

import zipfile
from pathlib import Path
from types import TracebackType
from typing import IO


def read_bytes(root: str, container: str, rel_path: str) -> bytes:
    """Bytes of one file: inside a Takeout zip part (`container`) or under `root`."""
    if container:
        with zipfile.ZipFile(container) as z:
            return z.read(rel_path)
    return (Path(root) / rel_path).read_bytes()


class MediaReader:
    """Same as `read_bytes`, but keeps zip parts open between calls (one central-directory
    read per part instead of one per photo). Use as a context manager. Read-only."""

    def __init__(self) -> None:
        self._zips: dict[str, zipfile.ZipFile] = {}

    def read(self, root: str, container: str, rel_path: str) -> bytes:
        if not container:
            return (Path(root) / rel_path).read_bytes()
        z = self._zips.get(container)
        if z is None:
            z = self._zips[container] = zipfile.ZipFile(container)
        return z.read(rel_path)

    def open(self, root: str, container: str, rel_path: str) -> IO[bytes]:
        """A read-only stream (for big videos). Caller closes it."""
        if not container:
            return (Path(root) / rel_path).open("rb")
        z = self._zips.get(container)
        if z is None:
            z = self._zips[container] = zipfile.ZipFile(container)
        return z.open(rel_path)

    def close(self) -> None:
        for z in self._zips.values():
            z.close()
        self._zips.clear()

    def __enter__(self) -> "MediaReader":
        return self

    def __exit__(
        self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
