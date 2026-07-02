#!/usr/bin/env bash
set -euo pipefail

PORT="${BACKEND_PORT:-8787}"

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
fi

uvicorn app.main:app --host "${BACKEND_BIND_HOST:-127.0.0.1}" --port "${PORT}"
