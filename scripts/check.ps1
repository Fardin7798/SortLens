# Run every check CI runs (Windows). Usage: .\scripts\check.ps1 [-BackendOnly]
param([switch]$BackendOnly)
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
if ($BackendOnly) { Write-Host "OK (backend only)"; exit 0 }

Write-Host "== frontend =="
Push-Location "$Root\frontend"
if (-not (Test-Path node_modules)) { Run "npm ci" }
Run "npm run lint"
Run "npm run build"
Pop-Location
Write-Host "OK: all checks passed"
