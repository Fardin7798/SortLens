#!/usr/bin/env bash
# Run every check CI runs. Usage: scripts/check.sh [--backend-only]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== backend =="
cd "$ROOT/backend"
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q

if [[ "${1:-}" == "--backend-only" ]]; then echo "OK (backend only)"; exit 0; fi

echo "== frontend =="
cd "$ROOT/frontend"
[[ -d node_modules ]] || npm ci
npm run lint
npm run build
echo "OK: all checks passed"
