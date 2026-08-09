#!/usr/bin/env bash
# Multi-architecture venv bootstrap for Omniflow.
#
# Supports:
#   macOS arm64 / x86_64
#   Linux x86_64 (CUDA or CPU), Linux aarch64 (CPU / PyPI)
#   Windows via Git Bash or use install.ps1
#
# Env overrides:
#   PYTHON=python3.12
#   VENV=/path/to/.venv
#   OMNIFLOW_TORCH=auto|cpu|cuda|default
#   OMNIFLOW_CUDA_CHANNEL=cu128|cu126|cu124
#   TORCH_CUDA_INDEX=https://download.pytorch.org/whl/cu128
#   OMNIFLOW_EXTRAS=dev          # pip extras, default: dev
#   SKIP_TORCH=1                 # only install core package
#   SKIP_PACKAGE=1               # only install torch
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-$ROOT/.venv}"
EXTRAS="${OMNIFLOW_EXTRAS:-dev}"

# --- pick python ---
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: Python not found: $PYTHON" >&2
  exit 1
fi

echo "==> Omniflow multi-arch install"
echo "    root:   $ROOT"
echo "    python: $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version(), platform.machine(), platform.system())'))"
echo "    venv:   $VENV"

if [[ ! -d "$VENV" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
if [[ -f "$VENV/bin/activate" ]]; then
  # Unix / macOS / WSL / Git Bash
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  PY="$VENV/bin/python"
  PIP="$VENV/bin/pip"
elif [[ -f "$VENV/Scripts/activate" ]]; then
  # Windows venv
  # shellcheck disable=SC1091
  source "$VENV/Scripts/activate"
  PY="$VENV/Scripts/python.exe"
  PIP="$VENV/Scripts/pip.exe"
else
  echo "ERROR: cannot find venv activate script under $VENV" >&2
  exit 1
fi

"$PY" -m pip install -U pip setuptools wheel

# --- platform report (stdlib only; package may not be installed yet) ---
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
echo ""
echo "==> Platform detection"
"$PY" - <<'PY' || true
import sys
sys.path.insert(0, ".")
from diary_app.core.platform_info import detect_platform, format_platform_report
print(format_platform_report())
prof = detect_platform()
if not prof.supported and prof.support_level == "unsupported":
    sys.exit(3)
PY
detect_rc=$?
if [[ "$detect_rc" -eq 3 ]]; then
  echo "ERROR: unsupported platform/Python. See notes above." >&2
  exit 3
fi

# --- torch (arch-correct wheels) ---
if [[ "${SKIP_TORCH:-0}" != "1" ]]; then
  echo ""
  echo "==> Installing PyTorch for this architecture"
  "$PY" -m diary_app.install_torch
else
  echo "==> SKIP_TORCH=1 — leaving existing torch as-is"
fi

# --- core package (does not reinstall torch; pyproject has no torch dep) ---
if [[ "${SKIP_PACKAGE:-0}" != "1" ]]; then
  echo ""
  echo "==> Installing omniflow core + extras [${EXTRAS}]"
  if [[ -f "$ROOT/pyproject.toml" ]]; then
    # Prefer editable install; torch is optional extra, already installed above
    if [[ -n "$EXTRAS" ]]; then
      "$PIP" install -e "${ROOT}[${EXTRAS}]"
    else
      "$PIP" install -e "${ROOT}"
    fi
  else
    "$PIP" install -r "$ROOT/diary_app/requirements-core.txt"
  fi
else
  echo "==> SKIP_PACKAGE=1"
fi

echo ""
echo "==> Doctor"
"$PY" -m diary_app doctor || true

echo ""
echo "Done. Activate with:"
if [[ -f "$VENV/bin/activate" ]]; then
  echo "  source $VENV/bin/activate"
else
  echo "  $VENV\\Scripts\\Activate.ps1   # PowerShell"
  echo "  $VENV\\Scripts\\activate.bat  # cmd"
fi
echo "Then:"
echo "  python -m diary_app doctor"
echo "  python -m diary_app devices"
echo "  python -m diary_app reindex"
echo "  python -m diary_app transcribe path/to/audio.wav --backend moss --device auto"
echo ""
echo "Force CPU wheels:   OMNIFLOW_TORCH=cpu $0"
echo "Force CUDA wheels:  OMNIFLOW_TORCH=cuda OMNIFLOW_CUDA_CHANNEL=cu128 $0"
echo "Skip reinstalling torch: SKIP_TORCH=1 $0"
