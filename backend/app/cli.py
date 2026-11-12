"""SortLens command line.

  sortlens serve                          start the local API on 127.0.0.1
  sortlens import-takeout PATH [PATH...]  read Takeout zip parts or an extracted Takeout folder
  sortlens import-folder PATH             read a laptop folder (recursive)
  sortlens stats                          counts from the local database
  sortlens people                         names tagged in Google Photos, with counts
  sortlens models download                fetch the two small CPU face models (once, ~39 MB)
  sortlens solo NAME --photo REF.jpg      list photos where NAME is alone (database only)
  sortlens solo-show RUN [--bucket B]     show a solo list: solo | group | check

Imports and solo only READ your files. Running an import again resumes and skips unchanged files.
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
from app.pipeline import solo
from app.pipeline.faces import SAME_PERSON, download_models


def _progress(c: dict[str, int]) -> None:
    print(
        f"\r  seen {c['seen']}  added {c['added']}  updated {c['updated']}  "
        f"unchanged {c['unchanged']}",
        end="",
        flush=True,
    )


def _solo(con: object, args: argparse.Namespace) -> int:
    from app.pipeline.faces import OpenCVEngine

    if not args.photo.is_file():
        print(f"not found: {args.photo}", file=sys.stderr)
        return 2
    try:
        engine = OpenCVEngine(settings.models_dir)
    except (ImportError, FileNotFoundError) as e:
        print(f"{e}\n(install: pip install 'sortlens[faces]'; then: sortlens models download)",
              file=sys.stderr)  # fmt: skip
        return 2

    def prog(c: dict[str, int]) -> None:
        print(f"\r  faces: {c['scanned'] + c['skipped']}/{c['todo']}  errors {c['errors']}",
              end="", flush=True)  # fmt: skip

    print("Finding faces. Your photos are only read; nothing is copied, moved or deleted.")
    try:
        res = solo.run(
            con,  # type: ignore[arg-type]
            engine,
            name=args.name,
            ref_photo=args.photo.read_bytes(),
            threshold=args.threshold or SAME_PERSON,
            tagged_only=args.tagged_only,
            batch_size=settings.batch_size,
            on_progress=prog,
        )
    except solo.ReferenceError_ as e:
        print(f"\n{e}. Use a clear photo where only {args.name} is visible.", file=sys.stderr)
        return 2
    print(f"\nList {res.run_id}: {json.dumps(res.counts)}")
    print(f"See it: sortlens solo-show {res.run_id} --bucket solo")
    return 0


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
    md = sub.add_parser("models", help="face models")
    md.add_argument("action", choices=["download"])
    so = sub.add_parser("solo", help="photos where one person is alone (lists only)")
    so.add_argument("name")
    so.add_argument("--photo", type=Path, required=True, help="clear photo with only that face")
    so.add_argument("--tagged-only", action="store_true", help="skip untagged photos (faster)")
    so.add_argument("--threshold", type=float, default=None)
    ss = sub.add_parser("solo-show", help="show a solo list")
    ss.add_argument("run", type=int)
    ss.add_argument("--bucket", choices=["solo", "group", "check"])
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host=settings.host, port=settings.port)
        return 0

    if args.cmd == "models":
        for p in download_models(settings.models_dir):
            print(f"ok  {p}")
        return 0

    con = store.connect(settings.db_path)
    if args.cmd == "solo":
        return _solo(con, args)
    if args.cmd == "solo-show":
        rows = solo.items(con, args.run, args.bucket)
        if not rows:
            print("nothing in this list")
        for r in rows:
            sim = "  -  " if r["similarity"] is None else f"{r['similarity']:.2f}"
            where = f"{r['container']}!{r['rel_path']}" if r["container"] else r["rel_path"]
            print(f"{r['bucket']:<6} {sim}  faces={r['n_faces']}  {where}  {r['reason']}")
        return 0
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
