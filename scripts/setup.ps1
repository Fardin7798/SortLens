<#
.SYNOPSIS
  One-command SortLens setup for Windows 10/11 (CPU only, no GPU needed).

.DESCRIPTION
  1. Installs uv (Python manager) if missing.
  2. Installs Python 3.12 and SortLens with exact pinned versions (backend\uv.lock).
  3. Downloads the two face models (~39 MB, SHA-256 checked) unless -NoFaces.
  4. Runs `sortlens doctor`.
  It never touches your photos. Safe to run again (it only fixes what is missing).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -DataDir "D:\SortLens Data"
#>
param(
    [string]$DataDir = "",   # where the database, models and undo log live (default: %USERPROFILE%\.sortlens)
    [switch]$NoFaces,        # skip OpenCV + face models (no solo list)
    [switch]$Dev             # also install test/lint tools
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"

function Step($n, $text) { Write-Host ""; Write-Host "[$n/4] $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "SETUP FAILED: $text" -ForegroundColor Red; exit 1 }
function Run([string]$exe, [string[]]$argList) {
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { Fail "$exe $($argList -join ' ')" }
}

if ($PSVersionTable.PSVersion.Major -lt 5) { Fail "PowerShell 5 or newer is needed." }
if (-not (Test-Path (Join-Path $Backend "uv.lock"))) { Fail "run this from the SortLens folder (backend\uv.lock not found)." }

Step 1 "uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found, installing it for this user (from astral.sh)..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "uv install did not work. Install it from https://docs.astral.sh/uv/ and run again." }
}
Run "uv" @("--version")

Step 2 "Python 3.12 + SortLens (pinned versions)"
$sync = @("sync", "--project", $Backend, "--locked", "--python", "3.12")
if (-not $NoFaces) { $sync += @("--extra", "faces") }
if ($Dev) { $sync += @("--extra", "dev") }
Run "uv" $sync
$Exe = Join-Path $Backend ".venv\Scripts\sortlens.exe"
if (-not (Test-Path $Exe)) { Fail "sortlens.exe not found after install." }

if ($DataDir -ne "") {
    $full = [System.IO.Path]::GetFullPath($DataDir)
    [Environment]::SetEnvironmentVariable("SORTLENS_DATA_DIR", $full, "User")
    $env:SORTLENS_DATA_DIR = $full
    Write-Host "Data folder set to $full (saved for this Windows user)."
}

Step 3 "face models"
if ($NoFaces) { Write-Host "skipped (-NoFaces)" } else { Run $Exe @("models", "download") }

Step 4 "check"
Run $Exe @("doctor")

Write-Host ""
Write-Host "SortLens is ready. Use it from this folder:" -ForegroundColor Green
Write-Host '  .\sortlens.cmd import-takeout "D:\Takeout\takeout-001.zip"'
Write-Host '  .\sortlens.cmd stats'
Write-Host '  .\sortlens.cmd serve      (local API on http://127.0.0.1:8765)'
