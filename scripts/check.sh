#!/usr/bin/env bash
# Run every check CI runs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== backend =="
cd "$ROOT/backend"
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
echo "OK: all checks passed"
