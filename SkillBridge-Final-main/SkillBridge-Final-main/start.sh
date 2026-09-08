#!/usr/bin/env bash
# SkillBridge single-command startup for bash / Git Bash / WSL / macOS / Linux.
#
# This is a thin wrapper around `npm start`, which is the single source of
# truth (see scripts/start.mjs). It works on every platform and handles the
# venv, frontend build, DB seed, and server startup automatically.
#
#   ./start.sh               start the app on http://localhost:8000
#   ./start.sh --reset       delete the database so it re-seeds
#   ./start.sh --dev         run the Vite dev server (live frontend reload)
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm is required to run SkillBridge. Install Node.js 18+ and try again." >&2
  exit 1
fi

exec npm start -- "$@"
