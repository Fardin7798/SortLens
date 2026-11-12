"""Read-only access to a media file's bytes, wherever the importer found it."""

import zipfile
from pathlib import Path


def read_bytes(root: str, container: str, rel_path: str) -> bytes:
    """Bytes of one file: inside a Takeout zip part (`container`) or under `root`."""
    if container:
        with zipfile.ZipFile(container) as z:
            return z.read(rel_path)
    return (Path(root) / rel_path).read_bytes()
