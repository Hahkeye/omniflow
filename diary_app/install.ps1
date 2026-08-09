# Multi-arch Omniflow install for Windows (x86_64 / ARM64).
# Usage (PowerShell):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\diary_app\install.ps1
#   $env:OMNIFLOW_TORCH='cpu'; .\diary_app\install.ps1
#   $env:OMNIFLOW_TORCH='cuda'; $env:OMNIFLOW_CUDA_CHANNEL='cu128'; .\diary_app\install.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$Venv = if ($env:VENV) { $env:VENV } else { Join-Path $Root ".venv" }
$Extras = if ($env:OMNIFLOW_EXTRAS) { $env:OMNIFLOW_EXTRAS } else { "dev" }

Write-Host "==> Omniflow Windows install"
Write-Host "    root:   $Root"
Write-Host "    python: $Python"
Write-Host "    venv:   $Venv"

if (-not (Test-Path $Venv)) {
  & $Python -m venv $Venv
}

$Py = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"
if (-not (Test-Path $Py)) {
  throw "venv python not found at $Py"
}

& $Py -m pip install -U pip setuptools wheel

$env:PYTHONPATH = "$Root;$env:PYTHONPATH"
Write-Host ""
Write-Host "==> Platform detection"
& $Py -c "from diary_app.core.platform_info import format_platform_report; print(format_platform_report())"

if ($env:SKIP_TORCH -ne "1") {
  Write-Host ""
  Write-Host "==> Installing PyTorch"
  & $Py -m diary_app.install_torch
} else {
  Write-Host "==> SKIP_TORCH=1"
}

if ($env:SKIP_PACKAGE -ne "1") {
  Write-Host ""
  Write-Host "==> Installing omniflow [$Extras]"
  if ($Extras) {
    & $Pip install -e "${Root}[$Extras]"
  } else {
    & $Pip install -e "$Root"
  }
}

Write-Host ""
Write-Host "==> Doctor"
& $Py -m diary_app doctor

Write-Host ""
Write-Host "Activate:  $Venv\Scripts\Activate.ps1"
Write-Host "Then:      python -m diary_app doctor"
