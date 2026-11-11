"""SortLens command line.

  sortlens serve                          start the local API on 127.0.0.1
  sortlens import-takeout PATH [PATH...]  read Takeout zip parts or an extracted Takeout folder
  sortlens import-folder PATH             read a laptop folder (recursive)
  sortlens stats                          counts from the local database
  sortlens people                         names tagged in Google Photos, with counts

Imports only READ your files. Running an import again resumes and skips unchanged files.
"""

import argparse
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.db import store
from app.importers.base import AlbumRecord
from app.importers.folder import scan_folder
from app.importers.takeout import scan_takeout


def _progress(c: dict[str, int]) -> None:
    print(
        f"\r  seen {c['seen']}  added {c['added']}  updated {c['updated']}  "
        f"unchanged {c['unchanged']}",
        end="",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sortlens", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="start the local API on 127.0.0.1")
    t = sub.add_parser("import-takeout", help="read a Google Takeout export (zips or folder)")
    t.add_argument("paths", nargs="+", type=Path)
    f = sub.add_parser("import-folder", help="read a laptop folder")
    f.add_argument("path", type=Path)
    sub.add_parser("stats", help="show counts")
    sub.add_parser("people", help="names tagged in Google Photos, with counts")
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host=settings.host, port=settings.port)
        return 0

    con = store.connect(settings.db_path)
    if args.cmd == "stats":
        print(json.dumps(store.stats(con), indent=2))
        return 0
    if args.cmd == "people":
        names = store.people(con)
        if not names:
            print("No tagged people found (tags come only from Takeout).")
        for name, n in names:
            print(f"{n:>7}  {name}")
        return 0

    if args.cmd == "import-takeout":
        missing = [p for p in args.paths if not p.exists()]
        if missing:
            print(f"not found: {', '.join(map(str, missing))}", file=sys.stderr)
            return 2
        albums: list[AlbumRecord] = []
        recs = scan_takeout(args.paths, albums)
        first = args.paths[0].resolve()
        source, root = "takeout", str(first.parent if first.is_file() else first)
    else:
        if not args.path.is_dir():
            print(f"not a folder: {args.path}", file=sys.stderr)
            return 2
        recs = scan_folder(args.path)
        source, root = "folder", str(args.path.resolve())

    print(f"Importing ({source}) from {root}. Your files are only read, never changed.")
    counts = store.import_records(
        con, recs, source=source, root=root, batch_size=settings.batch_size, on_progress=_progress
    )
    if args.cmd == "import-takeout":
        counts["albums"] = store.save_albums(con, albums)
    print(f"\nDone: {json.dumps(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def entry() -> None:
    raise SystemExit(main())
