# Launch the Omniflow desktop app (Tauri) with Python runtime wired correctly.
#
# Usage (PowerShell, from repo root):
#   .\scripts\launch-diary.ps1
#   .\scripts\launch-diary.ps1 -Setup          # bootstrap venv first
#   .\scripts\launch-diary.ps1 -Build          # production bundle
#   $env:OMNIFLOW_TORCH='cpu'; .\scripts\launch-diary.ps1 -Setup
#
# Sets DIARY_PROJECT_ROOT + DIARY_PYTHON so the shell can start the daemon.

param(
  [switch]$Setup,
  [switch]$Build,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
  Get-Content $MyInvocation.MyCommand.Path -TotalCount 12 | ForEach-Object {
    if ($_ -match '^#') { $_ -replace '^# ?', '' }
  }
  exit 0
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Host "==> Omniflow desktop launch"
Write-Host "    root: $Root"

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$NeedSetup = $Setup -or -not (Test-Path $VenvPy)

if ($NeedSetup) {
  if (-not (Test-Path $VenvPy)) {
    Write-Host "==> No .venv found — running install (this can take a while)…"
  } else {
    Write-Host "==> -Setup: re-running install…"
  }
  & (Join-Path $Root "diary_app\install.ps1")
}

if (-not (Test-Path $VenvPy)) {
  Write-Error "Python venv missing at $VenvPy. Run: .\diary_app\install.ps1  or  .\scripts\launch-diary.ps1 -Setup"
}

$env:DIARY_PROJECT_ROOT = "$Root"
$env:OMNIFLOW_ROOT = "$Root"
$env:DIARY_PYTHON = $VenvPy
$env:PYTHON = $VenvPy

Write-Host "    python: $VenvPy"
Write-Host "    DIARY_PROJECT_ROOT=$env:DIARY_PROJECT_ROOT"

Write-Host ""
Write-Host "==> Doctor (quick)"
try {
  & $VenvPy -m diary_app doctor
  if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: doctor reported issues. UI may still open; fix install if STT fails." -ForegroundColor Yellow
  }
} catch {
  Write-Host "WARNING: doctor failed: $_" -ForegroundColor Yellow
}

function Test-Command($Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "pnpm")) {
  Write-Error "pnpm not found. Install Node.js 20+ then:  npm install -g pnpm"
}
if (-not (Test-Command "cargo")) {
  Write-Error "Rust/cargo not found. Install from https://rustup.rs/"
}

Set-Location (Join-Path $Root "diary-frontend")
if (-not (Test-Path "node_modules")) {
  Write-Host "==> pnpm install"
  pnpm install
}

Write-Host ""
if ($Build) {
  Write-Host "==> pnpm tauri build"
  pnpm tauri build
} else {
  Write-Host "==> pnpm tauri dev"
  Write-Host "    Opening Diary… (first Rust compile can take several minutes)"
  pnpm tauri dev
}
