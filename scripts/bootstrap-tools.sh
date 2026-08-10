#!/usr/bin/env bash
# Install host tools needed to build/run the Diary desktop app (macOS / Linux).
#
# Usage:
#   bash scripts/bootstrap-tools.sh
#   bash scripts/bootstrap-tools.sh --yes          # no prompts
#   bash scripts/bootstrap-tools.sh --status       # report only
#   bash scripts/bootstrap-tools.sh --with-xcode   # macOS: prompt for CLT if needed
#
# Then:  bash scripts/launch-diary.sh --setup
set -euo pipefail

YES=0
STATUS=0
WITH_XCODE=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --status) STATUS=1 ;;
    --with-xcode) WITH_XCODE=1 ;;
    --help|-h)
      sed -n '2,12p' "$0" | sed -n 's/^# \{0,1\}//p'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

refresh_path_hint() {
  # rustup installs to ~/.cargo/bin — ensure current shell sees it
  if [[ -d "$HOME/.cargo/bin" ]]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  fi
  if [[ -d "$HOME/.local/share/pnpm" ]]; then
    export PATH="$HOME/.local/share/pnpm:$PATH"
  fi
}

show_status() {
  refresh_path_hint
  echo ""
  echo "=== Tool status ==="
  local all_ok=0
  for name in git python3 node pnpm cargo; do
    if have "$name"; then
      case "$name" in
        git) extra=$(git --version 2>/dev/null || true) ;;
        python3) extra=$(python3 -c 'import sys; print("python", "%d.%d"%sys.version_info[:2])' 2>/dev/null || true) ;;
        node) extra=$(node -v 2>/dev/null || true) ;;
        pnpm) extra=$(pnpm -v 2>/dev/null || true) ;;
        cargo) extra=$(cargo -V 2>/dev/null || true) ;;
      esac
      printf "  [OK]  %-8s %s\n" "$name" "$extra"
    else
      printf "  [!!]  %-8s missing\n" "$name"
      all_ok=1
    fi
  done
  return "$all_ok"
}

ensure_pnpm() {
  refresh_path_hint
  if have pnpm; then return 0; fi
  if have corepack; then
    echo "==> Enabling pnpm via corepack"
    corepack enable || true
    corepack prepare pnpm@latest --activate || true
  fi
  refresh_path_hint
  if have pnpm; then return 0; fi
  if have npm; then
    echo "==> Installing pnpm via npm -g"
    npm install -g pnpm
  fi
  refresh_path_hint
}

ensure_rust() {
  refresh_path_hint
  if have cargo; then return 0; fi
  echo "==> Installing Rust via rustup (default stable toolchain)…"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # shellcheck disable=SC1091
  [[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
  refresh_path_hint
}

install_via_brew() {
  have brew || return 1
  echo "==> Using Homebrew"
  local pkgs=()
  have git || pkgs+=(git)
  have python3 || pkgs+=(python@3.12)
  have node || pkgs+=(node)
  if ((${#pkgs[@]})); then
    brew install "${pkgs[@]}"
  fi
  ensure_pnpm
  ensure_rust
  return 0
}

install_via_apt() {
  have apt-get || return 1
  echo "==> Using apt"
  local pkgs=()
  have git || pkgs+=(git)
  have python3 || pkgs+=(python3 python3-venv python3-pip)
  have node || pkgs+=(nodejs npm)
  # curl for rustup
  have curl || pkgs+=(curl)
  if ((${#pkgs[@]})); then
    if [[ "$(id -u)" -eq 0 ]]; then
      apt-get update -y
      DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}"
    else
      sudo apt-get update -y
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}"
    fi
  fi
  ensure_pnpm
  ensure_rust
  return 0
}

install_via_dnf() {
  have dnf || return 1
  echo "==> Using dnf"
  local pkgs=()
  have git || pkgs+=(git)
  have python3 || pkgs+=(python3 python3-pip)
  have node || pkgs+=(nodejs npm)
  have curl || pkgs+=(curl)
  if ((${#pkgs[@]})); then
    if [[ "$(id -u)" -eq 0 ]]; then
      dnf install -y "${pkgs[@]}"
    else
      sudo dnf install -y "${pkgs[@]}"
    fi
  fi
  ensure_pnpm
  ensure_rust
  return 0
}

# ── main ─────────────────────────────────────────────────────────────────────
echo "==> Omniflow host tools bootstrap ($(uname -s))"

if [[ "$STATUS" -eq 1 ]]; then
  if show_status; then
    exit 0
  else
    exit 1
  fi
fi

if [[ "$YES" -ne 1 ]]; then
  cat <<EOF

This will install missing tools when a package manager is available:
  - Git, Python 3, Node.js, pnpm, Rust (rustup)

Package managers tried: Homebrew (macOS), apt, dnf.
You may be prompted for sudo.

EOF
  read -r -p "Continue? [Y/n] " ans || ans=y
  if [[ -n "${ans:-}" && ! "${ans}" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

# macOS Xcode CLT
if [[ "$(uname -s)" == "Darwin" ]]; then
  if ! xcode-select -p >/dev/null 2>&1; then
    echo "==> Xcode Command Line Tools missing"
    if [[ "$WITH_XCODE" -eq 1 ]] || [[ "$YES" -eq 1 ]]; then
      echo "    Launching installer (GUI dialog)…"
      xcode-select --install || true
      echo "    Finish the CLT install dialog, then re-run this script."
    else
      echo "    Run:  xcode-select --install"
      echo "    Or:   bash scripts/bootstrap-tools.sh --with-xcode"
    fi
  fi
fi

refresh_path_hint

if ! have git || ! have python3 || ! have node; then
  if install_via_brew; then
    :
  elif install_via_apt; then
    :
  elif install_via_dnf; then
    :
  else
    echo "No supported package manager found (brew/apt/dnf)." >&2
    echo "Install Git, Python 3.11+, and Node 20+ manually, then re-run with --status." >&2
  fi
else
  echo "    git/python3/node: present"
  ensure_pnpm
  ensure_rust
fi

# Always try pnpm/rust even if base tools existed
ensure_pnpm
ensure_rust

if show_status; then
  echo ""
  echo "Host tools look good. Next:"
  echo "  bash scripts/launch-diary.sh --setup"
  exit 0
else
  echo ""
  echo "Some tools still missing. Fix PATH or install manually, then:"
  echo "  bash scripts/bootstrap-tools.sh --status"
  exit 1
fi
