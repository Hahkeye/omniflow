#!/usr/bin/env bash
# Launch the Omniflow desktop app (Tauri) with Python runtime wired correctly.
#
# Usage (from repo root or anywhere):
#   bash scripts/launch-diary.sh
#   bash scripts/launch-diary.sh --setup            # bootstrap venv first
#   bash scripts/launch-diary.sh --bootstrap-tools  # install Git/Python/Node/Rust if missing
#   bash scripts/launch-diary.sh --build
#   OMNIFLOW_TORCH=cpu bash scripts/launch-diary.sh --setup
#
# Easiest first-time path:  bash scripts/get-started.sh
#
# Sets DIARY_PROJECT_ROOT + DIARY_PYTHON so the shell can start the daemon.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DO_SETUP=0
DO_BUILD=0
DO_BOOT_TOOLS=0
for arg in "$@"; do
  case "$arg" in
    --setup|-s) DO_SETUP=1 ;;
    --build|-b) DO_BUILD=1 ;;
    --bootstrap-tools|--tools|-t) DO_BOOT_TOOLS=1 ;;
    --help|-h)
      sed -n '2,14p' "$0" | sed -n 's/^# \{0,1\}//p'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

echo "==> Omniflow desktop launch"
echo "    root: $ROOT"

# shellcheck disable=SC1091
[[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
export PATH="${HOME}/.cargo/bin:${PATH}"

need_tools=0
for c in git python3 node cargo; do
  if ! command -v "$c" >/dev/null 2>&1; then
    need_tools=1
    break
  fi
done
if ! command -v pnpm >/dev/null 2>&1; then
  need_tools=1
fi

if [[ "$DO_BOOT_TOOLS" -eq 1 ]] || [[ "$need_tools" -eq 1 ]]; then
  if [[ "$need_tools" -eq 1 && "$DO_BOOT_TOOLS" -ne 1 ]]; then
    echo ""
    echo "Missing host tools (git / python3 / node / pnpm / cargo)."
    echo "Running bootstrap-tools (installs via brew/apt/dnf + rustup when possible)…"
  fi
  bash "$ROOT/scripts/bootstrap-tools.sh" --yes || {
    echo "ERROR: host tools still incomplete. Fix with:" >&2
    echo "  bash scripts/bootstrap-tools.sh --status" >&2
    echo "  bash scripts/bootstrap-tools.sh" >&2
    exit 1
  }
  # shellcheck disable=SC1091
  [[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
  export PATH="${HOME}/.cargo/bin:${PATH}"
fi

# ── Python runtime ────────────────────────────────────────────────────────────
if [[ "$DO_SETUP" -eq 1 ]] || [[ ! -d "$ROOT/.venv" ]]; then
  if [[ ! -d "$ROOT/.venv" ]]; then
    echo "==> No .venv found — running install (this can take a while)…"
  else
    echo "==> --setup: re-running install…"
  fi
  bash "$ROOT/diary_app/setup_venv.sh"
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
else
  echo "ERROR: Python venv missing at $ROOT/.venv" >&2
  echo "  Run:  bash diary_app/setup_venv.sh" >&2
  echo "  Or:   bash scripts/launch-diary.sh --setup" >&2
  exit 1
fi

export DIARY_PROJECT_ROOT="$ROOT"
export OMNIFLOW_ROOT="$ROOT"
export DIARY_PYTHON="$PY"
export PYTHON="$PY"

echo "    python: $PY"
echo "    DIARY_PROJECT_ROOT=$DIARY_PROJECT_ROOT"

echo ""
echo "==> Doctor (quick)"
if ! "$PY" -m diary_app doctor; then
  echo ""
  echo "WARNING: doctor reported issues. The UI may still open; fix install if STT fails." >&2
  echo "  python -m diary_app.install_torch" >&2
  echo "  bash diary_app/setup_venv.sh" >&2
fi

# ── Frontend / Tauri toolchain ────────────────────────────────────────────────
if ! command -v pnpm >/dev/null 2>&1; then
  echo "ERROR: pnpm not found after bootstrap. Try: corepack enable && corepack prepare pnpm@latest --activate" >&2
  exit 1
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "ERROR: cargo not found after bootstrap. Install Rust: https://rustup.rs/" >&2
  exit 1
fi

cd "$ROOT/diary-frontend"
if [[ ! -d node_modules ]]; then
  echo "==> pnpm install"
  pnpm install
fi

echo ""
if [[ "$DO_BUILD" -eq 1 ]]; then
  echo "==> pnpm tauri build"
  exec pnpm tauri build
else
  echo "==> pnpm tauri dev"
  echo "    Opening Diary… (first Rust compile can take several minutes)"
  exec pnpm tauri dev
fi
