@echo off
rem Runs SortLens from this folder. Set it up once with: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
if not exist "%~dp0backend\.venv\Scripts\sortlens.exe" (
  echo SortLens is not set up yet. Run: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  exit /b 1
)
"%~dp0backend\.venv\Scripts\sortlens.exe" %*
