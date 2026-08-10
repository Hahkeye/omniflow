# Launch the Omniflow desktop app (Tauri) with Python runtime wired correctly.
#
# Usage (PowerShell, from repo root):
#   .\scripts\launch-diary.ps1
#   .\scripts\launch-diary.ps1 -Setup
#   .\scripts\launch-diary.ps1 -BootstrapTools     # install Git/Python/Node/Rust if missing
#   .\scripts\launch-diary.ps1 -WithBuildTools     # also VS C++ Build Tools (large)
#   .\scripts\launch-diary.ps1 -Build
#   $env:OMNIFLOW_TORCH='cpu'; .\scripts\launch-diary.ps1 -Setup
#
# Easiest first-time path:  .\scripts\get-started.ps1
#
# Sets DIARY_PROJECT_ROOT + DIARY_PYTHON so the shell can start the daemon.

param(
  [switch]$Setup,
  [switch]$Build,
  [switch]$BootstrapTools,
  [switch]$WithBuildTools,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
  Get-Content $MyInvocation.MyCommand.Path -TotalCount 16 | ForEach-Object {
    if ($_ -match '^#') { $_ -replace '^# ?', '' }
  }
  exit 0
}

function Refresh-Path {
  $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = @($machine, $user, "$env:USERPROFILE\.cargo\bin", "$env:LOCALAPPDATA\pnpm") -join ";"
}

function Test-Cmd([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
Refresh-Path

Write-Host "==> Omniflow desktop launch"
Write-Host "    root: $Root"

$needTools = -not (
  (Test-Cmd "git") -and
  ((Test-Cmd "python") -or (Test-Cmd "py") -or (Test-Cmd "python3")) -and
  (Test-Cmd "node") -and
  (Test-Cmd "pnpm") -and
  (Test-Cmd "cargo")
)

if ($BootstrapTools -or $needTools) {
  if ($needTools -and -not $BootstrapTools) {
    Write-Host ""
    Write-Host "Missing host tools (git / python / node / pnpm / cargo)."
    Write-Host "Running bootstrap-tools (winget + rustup when possible)…"
  }
  $bootArgs = @("-Yes")
  if ($WithBuildTools) { $bootArgs += "-WithBuildTools" }
  & (Join-Path $Root "scripts\bootstrap-tools.ps1") @bootArgs
  Refresh-Path
}

# ── Python runtime ────────────────────────────────────────────────────────────
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

if (-not (Test-Cmd "pnpm")) {
  Write-Error "pnpm not found. Run: .\scripts\bootstrap-tools.ps1   then open a new terminal."
}
if (-not (Test-Cmd "cargo")) {
  Write-Error "cargo not found. Run: .\scripts\bootstrap-tools.ps1   then open a new terminal."
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
  if (-not $WithBuildTools) {
    Write-Host "    If link.exe/cl.exe errors appear, re-run:  .\scripts\bootstrap-tools.ps1 -WithBuildTools" -ForegroundColor DarkYellow
  }
  pnpm tauri dev
}
