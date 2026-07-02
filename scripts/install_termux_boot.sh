#!/data/data/com.termux/files/usr/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR="${BACKEND_PROJECT_DIR:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
BOOT_DIR="${TERMUX_BOOT_DIR:-${HOME}/.termux/boot}"
BOOT_SCRIPT="${BOOT_DIR}/kakao-termux-back.sh"

mkdir -p "${BOOT_DIR}" "${PROJECT_DIR}/data/logs"

cat > "${BOOT_SCRIPT}" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
set -eu

cd "${PROJECT_DIR}"
export BACKEND_BIND_HOST="\${BACKEND_BIND_HOST:-127.0.0.1}"
export BACKEND_PORT="\${BACKEND_PORT:-8787}"
export ANDROID_BRIDGE_MODE="\${ANDROID_BRIDGE_MODE:-am_broadcast}"
export LOG_PII="\${LOG_PII:-false}"
export ENABLE_WAKE_LOCK="\${ENABLE_WAKE_LOCK:-true}"

exec "${PROJECT_DIR}/scripts/run_termux_server.sh" >> "${PROJECT_DIR}/data/logs/server.log" 2>&1
EOF

chmod 700 "${BOOT_SCRIPT}"
printf 'installed Termux:Boot script: %s\n' "${BOOT_SCRIPT}"
