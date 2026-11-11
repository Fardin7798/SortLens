# Run every check CI runs (Windows).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
function Run($cmd) { Write-Host "> $cmd"; Invoke-Expression $cmd; if ($LASTEXITCODE -ne 0) { throw "FAILED: $cmd" } }

Write-Host "== backend =="
Push-Location "$Root\backend"
Run "uv run ruff check ."
Run "uv run ruff format --check ."
Run "uv run mypy app"
Run "uv run pytest -q"
Pop-Location
Write-Host "OK: all checks passed"
