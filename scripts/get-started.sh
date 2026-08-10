#!/usr/bin/env bash
# One-shot onboarding: host tools → Omniflow venv → open Diary.
#
# Usage:
#   bash scripts/get-started.sh
#   OMNIFLOW_TORCH=cpu bash scripts/get-started.sh
#   bash scripts/get-started.sh --with-xcode   # macOS CLT prompt
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

EXTRA_BOOT=()
for arg in "$@"; do
  case "$arg" in
    --with-xcode) EXTRA_BOOT+=(--with-xcode) ;;
    --help|-h)
      sed -n '2,8p' "$0" | sed -n 's/^# \{0,1\}//p'
      exit 0
      ;;
  esac
done

cat <<EOF

  Omniflow — get started
  ======================
  1) Install host tools (Git, Python, Node, Rust)
  2) Create Python venv + deps
  3) Launch Diary (Tauri)

EOF

bash "$ROOT/scripts/bootstrap-tools.sh" --yes "${EXTRA_BOOT[@]+"${EXTRA_BOOT[@]}"}" || {
  echo "WARNING: tool bootstrap had issues — if PATH was updated, open a new shell." >&2
}

# rustup env for this shell
# shellcheck disable=SC1091
[[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
export PATH="${HOME}/.cargo/bin:${PATH}"

exec bash "$ROOT/scripts/launch-diary.sh" --setup
