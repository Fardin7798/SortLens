"""`sortlens serve` starts the local API. More commands (scan, import-takeout) come in v1."""

import argparse

import uvicorn

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="sortlens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="start the local API on 127.0.0.1")
    args = parser.parse_args()
    if args.cmd == "serve":
        uvicorn.run("app.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
