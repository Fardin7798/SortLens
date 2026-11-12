"""SortLens command line.

  sortlens serve                          start the local API on 127.0.0.1
  sortlens import-takeout PATH [PATH...]  read Takeout zip parts or an extracted Takeout folder
  sortlens import-folder PATH             read a laptop folder (recursive)
  sortlens stats                          counts from the local database
  sortlens dates                          best "taken at" date for every file (resumes)
  sortlens dupes [--no-near]              duplicate lists: exact, near, album copies, -edited
  sortlens dupes-show RUN [--kind K]      show them (keep first; nothing is deleted)
  sortlens people                         names tagged in Google Photos, with counts
  sortlens models download                fetch the two small CPU face models (once, ~39 MB)
  sortlens solo NAME --photo REF.jpg      list photos where NAME is alone (database only)
  sortlens solo-show RUN [--bucket B]     show a solo list: solo | group | check

Imports, dates, dupes and solo only READ your files. Running an import again resumes and skips unchanged files.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.core.config import settings
from app.db import store
from app.pipeline import dupes, solo, steps
from app.pipeline.dates import run_dates
from app.pipeline.faces import SAME_PERSON, download_models


def _progress(c: dict[str, int]) -> None:
    print(
        f"\r  seen {c['seen']}  added {c['added']}  updated {c['updated']}  "
        f"unchanged {c['unchanged']}",
        end="",
        flush=True,
    )


def _solo(con: sqlite3.Connection, args: argparse.Namespace) -> int:
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
            con,
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
    sub.add_parser("dates", help="best taken-at date for every file (resumes)")
    du = sub.add_parser("dupes", help="duplicate lists (database only)")
    du.add_argument("--no-near", action="store_true", help="exact copies only (faster)")
    du.add_argument("--distance", type=int, default=dupes.NEAR_DISTANCE, help="near: max bits")
    ds = sub.add_parser("dupes-show", help="show duplicate groups")
    ds.add_argument("run", type=int)
    ds.add_argument("--kind", choices=["exact", "near", "album_copy", "edited"])
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
    if args.cmd == "dates":
        print("Reading dates. Your files are only read, never changed.")
        c = run_dates(
            con,
            batch_size=settings.batch_size,
            on_progress=lambda c: print(f"\r  {c['done']}/{c['todo']}", end="", flush=True),
        )
        print(f"\nDone: {json.dumps(c)}")
        return 0
    if args.cmd == "dupes":
        print("Finding duplicates. Your files are only read; nothing is moved or deleted.")
        res = dupes.run(
            con,
            near=not args.no_near,
            near_distance=args.distance,
            batch_size=settings.batch_size,
            on_progress=lambda c: print(
                f"\r  files {c['hashed'] + c['cached']}/{c['todo']}  errors {c['errors']}",
                end="",
                flush=True,
            ),
        )
        print(f"\nList {res.run_id}: {json.dumps(res.counts)}")
        print(f"See it: sortlens dupes-show {res.run_id} --kind exact")
        return 0
    if args.cmd == "dupes-show":
        gs = dupes.groups(con, args.run, args.kind)
        if not gs:
            print("nothing in this list")
        for g in gs:
            print(f"[{g['kind']} #{g['group']}]")
            for f in g["files"]:
                where = f"{f['container']}!{f['rel_path']}" if f["container"] else f["rel_path"]
                d = "" if f["distance"] is None else f"  ({f['distance']} bits)"
                print(f"  {f['role']:<5} {f['size']:>10}  {where}{d}")
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

    try:
        if args.cmd == "import-takeout":
            print("Importing Google Takeout. Your files are only read, never changed.")
            counts = steps.import_takeout(
                con, args.paths, batch_size=settings.batch_size, on_progress=_progress
            )
        else:
            print(f"Importing folder {args.path}. Your files are only read, never changed.")
            counts = steps.import_folder(
                con, args.path, batch_size=settings.batch_size, on_progress=_progress
            )
    except (FileNotFoundError, NotADirectoryError) as e:
        print(e, file=sys.stderr)
        return 2
    print(f"\nDone: {json.dumps(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def entry() -> None:
    raise SystemExit(main())
