# One-shot Windows onboarding: host tools → Omniflow venv → open Diary.
#
# Usage:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\get-started.ps1
#   .\scripts\get-started.ps1 -CpuOnly
#   .\scripts\get-started.ps1 -WithBuildTools   # first-time Tauri compile on a clean PC

param(
  [switch]$CpuOnly,
  [switch]$WithBuildTools,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
  @'
Omniflow Windows get-started (tools + app):

  .\scripts\get-started.ps1
  .\scripts\get-started.ps1 -CpuOnly
  .\scripts\get-started.ps1 -WithBuildTools
'@ | Write-Host
  exit 0
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Host @"

  Omniflow — get started (Windows)
  ================================
  1) Install host tools (Git, Python, Node, Rust)
  2) Create Python venv + deps
  3) Launch Diary (Tauri)

"@ -ForegroundColor Cyan

$bootArgs = @("-Yes")
if ($WithBuildTools) { $bootArgs += "-WithBuildTools" }
& (Join-Path $Root "scripts\bootstrap-tools.ps1") @bootArgs
if ($LASTEXITCODE -ne 0) {
  Write-Host "Tool bootstrap reported issues — continuing if PATH is only stale." -ForegroundColor Yellow
  Write-Host "Open a new PowerShell if git/python/node/cargo are still missing." -ForegroundColor Yellow
}

# Refresh PATH for this session
$machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$user = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = @($machine, $user, "$env:USERPROFILE\.cargo\bin") -join ";"

if ($CpuOnly) {
  $env:OMNIFLOW_TORCH = "cpu"
}

& (Join-Path $Root "scripts\launch-diary.ps1") -Setup
