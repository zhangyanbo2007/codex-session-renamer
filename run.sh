#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="${PYTHON}"
elif [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi
HOST="${SESSION_RENAMER_HOST:-127.0.0.1}"
PORT="${SESSION_RENAMER_PORT:-8891}"

cd "${PROJECT_DIR}"
exec "${PYTHON_BIN}" -m uvicorn "session_renamer.app:create_app" --factory --host "${HOST}" --port "${PORT}"
