# Install host tools needed to build/run the Diary desktop app on Windows.
#
# Tries to make "you still need Git/Python/Node/Rust" a one-shot instead of a scavenger hunt.
#
# Usage (PowerShell, Admin recommended for winget / Build Tools):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\bootstrap-tools.ps1
#   .\scripts\bootstrap-tools.ps1 -Yes              # no prompts
#   .\scripts\bootstrap-tools.ps1 -WithBuildTools   # also VS C++ tools (large, for Tauri compile)
#   .\scripts\bootstrap-tools.ps1 -Status           # report only
#
# Then:  .\scripts\launch-diary.ps1 -Setup

param(
  [switch]$Yes,
  [switch]$WithBuildTools,
  [switch]$Status,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
  @'
Install host tools for Omniflow Diary on Windows (Git, Python, Node/pnpm, Rust).

  .\scripts\bootstrap-tools.ps1
  .\scripts\bootstrap-tools.ps1 -Yes
  .\scripts\bootstrap-tools.ps1 -WithBuildTools   # ~several GB; needed once for first Tauri build
  .\scripts\bootstrap-tools.ps1 -Status

After tools are OK:
  .\scripts\launch-diary.ps1 -Setup
'@ | Write-Host
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

function Get-PythonCmd {
  foreach ($c in @("python", "python3", "py")) {
    if (Test-Cmd $c) {
      try {
        if ($c -eq "py") {
          $v = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
          if ($LASTEXITCODE -eq 0 -and $v) { return @{ Cmd = "py"; Args = @("-3"); Version = $v.Trim() } }
        } else {
          $v = & $c -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
          if ($LASTEXITCODE -eq 0 -and $v) { return @{ Cmd = $c; Args = @(); Version = $v.Trim() } }
        }
      } catch {}
    }
  }
  return $null
}

function Ensure-Winget {
  if (Test-Cmd "winget") { return $true }
  Write-Host "winget not found. Install 'App Installer' from the Microsoft Store, then re-run." -ForegroundColor Yellow
  return $false
}

function Winget-Install([string]$Id, [string]$Label) {
  Write-Host "==> Installing $Label ($Id) via winget…"
  # --accept-package-agreements may need admin for some packages
  & winget install --id $Id -e --accept-package-agreements --accept-source-agreements --disable-interactivity
  Refresh-Path
}

function Ensure-Pnpm {
  Refresh-Path
  if (Test-Cmd "pnpm") { return }
  if (Test-Cmd "corepack") {
    Write-Host "==> Enabling pnpm via corepack"
    try {
      & corepack enable 2>$null
      & corepack prepare pnpm@latest --activate
    } catch {
      Write-Host "corepack prepare failed: $_" -ForegroundColor Yellow
    }
    Refresh-Path
  }
  if (-not (Test-Cmd "pnpm") -and (Test-Cmd "npm")) {
    Write-Host "==> Installing pnpm via npm -g"
    & npm install -g pnpm
    Refresh-Path
  }
}

function Ensure-Rust {
  Refresh-Path
  if (Test-Cmd "cargo") { return }
  Write-Host "==> Installing Rust (rustup, default toolchain)…"
  $rustup = Join-Path $env:TEMP "rustup-init.exe"
  Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustup
  & $rustup -y --default-toolchain stable
  Refresh-Path
  if (-not (Test-Cmd "cargo")) {
    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    if (Test-Path (Join-Path $cargoBin "cargo.exe")) {
      $env:Path = "$cargoBin;$env:Path"
    }
  }
}

function Ensure-BuildTools {
  # Check for link.exe / cl.exe rough presence
  if ((Test-Cmd "cl") -or (Test-Cmd "link")) {
    Write-Host "    C++ build tools appear present"
    return
  }
  # vswhere
  $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
  if (Test-Path $vswhere) {
    $inst = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($inst) {
      Write-Host "    VS C++ tools found at $inst"
      return
    }
  }
  if (-not $WithBuildTools) {
    Write-Host ""
    Write-Host "NOTE: Visual Studio C++ Build Tools not detected." -ForegroundColor Yellow
    Write-Host "  First 'pnpm tauri dev' compile needs them (~several GB download)."
    Write-Host "  Re-run with:  .\scripts\bootstrap-tools.ps1 -WithBuildTools"
    Write-Host "  Or install: https://visualstudio.microsoft.com/visual-cpp-build-tools/"
    return
  }
  if (-not (Ensure-Winget)) { return }
  Write-Host "==> Installing VS 2022 Build Tools (VC++ workload) — large download…"
  # winget package id for Build Tools
  & winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-package-agreements --accept-source-agreements --disable-interactivity --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  Refresh-Path
}

function Show-Status {
  Refresh-Path
  Write-Host ""
  Write-Host "=== Tool status ===" -ForegroundColor Cyan
  $rows = @(
    @{ Name = "git";    Ok = (Test-Cmd "git"); Extra = if (Test-Cmd "git") { (git --version) } else { "missing" } }
    @{ Name = "python"; Ok = $false; Extra = "missing" }
    @{ Name = "node";   Ok = (Test-Cmd "node"); Extra = if (Test-Cmd "node") { (node -v) } else { "missing" } }
    @{ Name = "pnpm";   Ok = (Test-Cmd "pnpm"); Extra = if (Test-Cmd "pnpm") { (pnpm -v) } else { "missing" } }
    @{ Name = "cargo";  Ok = (Test-Cmd "cargo"); Extra = if (Test-Cmd "cargo") { (cargo -V) } else { "missing" } }
    @{ Name = "winget"; Ok = (Test-Cmd "winget"); Extra = if (Test-Cmd "winget") { "ok" } else { "missing" } }
  )
  $py = Get-PythonCmd
  if ($py) {
    $rows[1].Ok = $true
    $rows[1].Extra = "python $($py.Version) ($($py.Cmd))"
  }
  $allOk = $true
  foreach ($r in $rows) {
    $mark = if ($r.Ok) { "[OK]" } else { "[!!]"; $allOk = $false }
    Write-Host ("  {0,-6} {1,-8} {2}" -f $mark, $r.Name, $r.Extra)
  }
  return $allOk
}

# ── main ─────────────────────────────────────────────────────────────────────
Write-Host "==> Omniflow host tools bootstrap (Windows)"
Refresh-Path

if ($Status) {
  $ok = Show-Status
  if (-not $ok) { exit 1 }
  exit 0
}

if (-not $Yes) {
  Write-Host @"

This will install missing tools using winget / rustup when possible:
  - Git
  - Python 3.12
  - Node.js LTS (+ pnpm via corepack)
  - Rust (rustup)

Optional (-WithBuildTools): Visual Studio C++ Build Tools (large).

"@
  $ans = Read-Host "Continue? [Y/n]"
  if ($ans -and $ans -notmatch '^[Yy]') {
    Write-Host "Aborted."
    exit 0
  }
}

if (-not (Ensure-Winget)) {
  Write-Host "Cannot auto-install without winget. Install tools manually, then re-run -Status." -ForegroundColor Red
  exit 1
}

# Git
if (-not (Test-Cmd "git")) {
  Winget-Install "Git.Git" "Git"
} else {
  Write-Host "    git: already present"
}

# Python
$py = Get-PythonCmd
if (-not $py) {
  Winget-Install "Python.Python.3.12" "Python 3.12"
  Refresh-Path
  $py = Get-PythonCmd
  if (-not $py) {
    Write-Host "Python installed but not on PATH yet. Open a new terminal, or enable" -ForegroundColor Yellow
    Write-Host "  'Add python.exe to PATH' in the Python installer, then re-run." -ForegroundColor Yellow
  }
} else {
  Write-Host "    python: $($py.Version) already present"
}

# Node
if (-not (Test-Cmd "node")) {
  Winget-Install "OpenJS.NodeJS.LTS" "Node.js LTS"
} else {
  Write-Host "    node: already present ($(node -v))"
}

Ensure-Pnpm
if (Test-Cmd "pnpm") {
  Write-Host "    pnpm: $(pnpm -v)"
} else {
  Write-Host "pnpm still missing — after Node is on PATH:  corepack enable && corepack prepare pnpm@latest --activate" -ForegroundColor Yellow
}

# Rust
if (-not (Test-Cmd "cargo")) {
  Ensure-Rust
} else {
  Write-Host "    cargo: already present ($(cargo -V))"
}

Ensure-BuildTools

# WebView2 is usually present; hint only if clearly missing
$wv = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue
if (-not $wv) {
  Write-Host "NOTE: WebView2 runtime may be missing. Install from:" -ForegroundColor Yellow
  Write-Host "  https://developer.microsoft.com/microsoft-edge/webview2/"
}

$ok = Show-Status
Write-Host ""
if ($ok) {
  Write-Host "Host tools look good. Next:" -ForegroundColor Green
  Write-Host "  cd $(Resolve-Path (Join-Path $PSScriptRoot '..'))"
  Write-Host "  .\scripts\launch-diary.ps1 -Setup"
  Write-Host ""
  Write-Host "Tip: open a NEW PowerShell window if commands were just installed (PATH refresh)."
  exit 0
} else {
  Write-Host "Some tools are still missing. Open a new terminal and re-run:" -ForegroundColor Yellow
  Write-Host "  .\scripts\bootstrap-tools.ps1 -Status"
  exit 1
}
