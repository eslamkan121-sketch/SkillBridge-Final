#!/usr/bin/env bash
# One-time environment setup (idempotent).
set -euo pipefail
cd "$(dirname "$0")/.."

resolve_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  for candidate in \
    "/c/Users/khale/AppData/Local/Programs/Python/Python312/python.exe" \
    "/mnt/c/Users/khale/AppData/Local/Programs/Python/Python312/python.exe" \
    "$USERPROFILE/AppData/Local/Programs/Python/Python312/python.exe" \
    "/usr/bin/python3"; do
    if [ -n "$candidate" ] && [ -e "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

resolve_venv_python() {
  local venv_dir="${1:-.venv}"
  local candidate=""
  for candidate in \
    "$venv_dir/Scripts/python.exe" \
    "$venv_dir/Scripts/python" \
    "$venv_dir/bin/python" \
    "$venv_dir/bin/python3"; do
    if [ -x "$candidate" ]; then
      if [ "${candidate#/}" = "$candidate" ]; then
        candidate="$PWD/$candidate"
      fi
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="$(resolve_python)" || {
  echo "Python 3 is required to run SkillBridge." >&2
  exit 1
}
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
VENV_PY="$(resolve_venv_python "$VENV_DIR")" || {
  echo "Virtual environment is incomplete." >&2
  exit 1
}
"$VENV_PY" -m pip install --quiet -r backend/requirements.txt
(cd frontend && npm install --silent)
echo "Setup complete."
