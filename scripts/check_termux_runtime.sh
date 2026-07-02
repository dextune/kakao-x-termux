#!/data/data/com.termux/files/usr/bin/sh
set -eu

PORT="${BACKEND_PORT:-8787}"
HEALTH_URL="${BACKEND_HEALTH_URL:-http://127.0.0.1:${PORT}/health}"

ok=true

check_command() {
  name="$1"
  if command -v "${name}" >/dev/null 2>&1; then
    printf 'OK   %s command found\n' "${name}"
  else
    printf 'WARN %s command not found\n' "${name}"
    ok=false
  fi
}

check_command python
check_command pip
check_command sqlite3
check_command git
check_command git-lfs
check_command curl
check_command ssh
check_command am

if command -v fuser >/dev/null 2>&1 || command -v lsof >/dev/null 2>&1; then
  printf 'OK   port cleanup command found\n'
else
  printf 'WARN neither fuser nor lsof command found\n'
  ok=false
fi

if command -v termux-wake-lock >/dev/null 2>&1; then
  printf 'OK   termux-wake-lock command found\n'
else
  printf 'WARN termux-wake-lock command not found; install Termux:API or run wake-lock manually if available\n'
  ok=false
fi

if command -v curl >/dev/null 2>&1; then
  if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
    printf 'OK   backend health reachable: %s\n' "${HEALTH_URL}"
  else
    printf 'WARN backend health not reachable: %s\n' "${HEALTH_URL}"
    ok=false
  fi
else
  printf 'WARN curl command not found; cannot check backend health\n'
  ok=false
fi

if python -m uvicorn --version >/dev/null 2>&1; then
  printf 'OK   uvicorn module import succeeded\n'
else
  printf 'WARN uvicorn module import failed; install requirements.txt first\n'
  ok=false
fi

printf 'INFO Android settings must exclude Termux and kakao-bridge-app from battery optimization.\n'
printf 'INFO Reboot validation requires Termux:Boot app permission and one manual Termux launch after install.\n'

if [ "${ok}" = "true" ]; then
  exit 0
fi
exit 1
