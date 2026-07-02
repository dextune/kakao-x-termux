#!/data/data/com.termux/files/usr/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
PORT="${BACKEND_PORT:-8787}"
HOST="${BACKEND_BIND_HOST:-127.0.0.1}"

cd "${PROJECT_DIR}"
mkdir -p data/logs

kill_port() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
    sleep 1
  fi
  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"${PORT}" 2>/dev/null || true)
    if [ -n "${pids}" ]; then
      # shellcheck disable=SC2086
      kill ${pids} 2>/dev/null || true
      sleep 1
    fi
  fi
  pids=$(ps -ef 2>/dev/null | grep "python -m uvicorn app.main:app --host ${HOST} --port ${PORT}" | grep -v grep | tr -s " " | cut -d " " -f 2 || true)
  if [ -n "${pids}" ]; then
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"${PORT}" 2>/dev/null || true)
    if [ -n "${pids}" ]; then
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
    fi
  fi
}

if [ "${ENABLE_WAKE_LOCK:-false}" = "true" ] && command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock || true
fi

kill_port

if [ ! -d ".venv" ] || [ ! -x ".venv/bin/python" ]; then
  scripts/install_termux_requirements.sh
fi
. ".venv/bin/activate"

if ! python -c "import fastapi, uvicorn, pydantic_core" >/dev/null 2>&1; then
  deactivate 2>/dev/null || true
  scripts/install_termux_requirements.sh
  . ".venv/bin/activate"
fi

export BACKEND_BIND_HOST="${HOST}"
export BACKEND_PORT="${PORT}"
export BRIDGE_SHARED_SECRET="${BRIDGE_SHARED_SECRET:-shared-secret}"
export ANDROID_BRIDGE_MODE="${ANDROID_BRIDGE_MODE:-am_broadcast}"
export LOG_PII="${LOG_PII:-false}"

python scripts/init_db.py
exec python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
