#!/data/data/com.termux/files/usr/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
PYDANTIC_CORE_VERSION="${PYDANTIC_CORE_VERSION:-2.46.3}"
PYDANTIC_VERSION="${PYDANTIC_VERSION:-2.13.3}"
REPO_USER="${PYDANTIC_CORE_REPO_USER:-Eutalix}"
REPO_NAME="${PYDANTIC_CORE_REPO_NAME:-android-pydantic-core}"
RELEASE_TAG="${PYDANTIC_CORE_RELEASE_TAG:-v${PYDANTIC_CORE_VERSION}}"

log() {
  printf 'INFO %s\n' "$*"
}

ensure_termux_package() {
  command_name="$1"
  package_name="$2"

  if command -v "${command_name}" >/dev/null 2>&1; then
    log "${package_name} already installed"
    return 0
  fi

  log "installing missing Termux package: ${package_name}"
  pkg install -y "${package_name}"
}

install_python_deps() {
  cd "${PROJECT_DIR}"

  if [ ! -d ".venv" ]; then
    python -m venv .venv
  fi
  . ".venv/bin/activate"

  python -m pip install --upgrade pip

  PY_TAG=$(python - <<'PY'
import sys
print(f"cp{sys.version_info.major}{sys.version_info.minor}")
PY
)

  ARCH=$(uname -m)
  case "${ARCH}" in
    aarch64) PLAT_TAG="linux_aarch64" ;;
    armv7l|armv8l) PLAT_TAG="linux_armv7l" ;;
    x86_64) PLAT_TAG="linux_x86_64" ;;
    i686|i386) PLAT_TAG="linux_i686" ;;
    *)
      printf 'unsupported architecture: %s\n' "${ARCH}" >&2
      exit 1
      ;;
  esac

  TMP_DIR=$(mktemp -d)
  cleanup() {
    rm -rf "${TMP_DIR}"
  }
  trap cleanup EXIT

  RELEASE_JSON="${TMP_DIR}/release.json"
  API_URL="https://api.github.com/repos/${REPO_USER}/${REPO_NAME}/releases/tags/${RELEASE_TAG}"
  curl -fsSL "${API_URL}" -o "${RELEASE_JSON}"

  ASSET_INFO=$(python - "${RELEASE_JSON}" "${PY_TAG}" "${PLAT_TAG}" "${PYDANTIC_CORE_VERSION}" <<'PY'
import json
import sys

path, py_tag, plat_tag, version = sys.argv[1:5]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

prefix = f"pydantic_core-{version}-"
for asset in data.get("assets", []):
    name = asset.get("name", "")
    if name.startswith(prefix) and py_tag in name and plat_tag in name and name.endswith(".whl"):
        print(asset["browser_download_url"])
        print(name)
        raise SystemExit(0)

raise SystemExit(f"compatible pydantic-core wheel not found: version={version} py={py_tag} platform={plat_tag}")
PY
)

  DOWNLOAD_URL=$(printf '%s\n' "${ASSET_INFO}" | sed -n '1p')
  ORIGINAL_NAME=$(printf '%s\n' "${ASSET_INFO}" | sed -n '2p')
  ORIGINAL_WHEEL="${TMP_DIR}/${ORIGINAL_NAME}"
  curl -fL -o "${ORIGINAL_WHEEL}" "${DOWNLOAD_URL}"

  WHEEL_TAG=$(python - "${ORIGINAL_WHEEL}" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as wheel:
    for name in wheel.namelist():
        if name.endswith(".dist-info/WHEEL"):
            for line in wheel.read(name).decode("utf-8").splitlines():
                if line.startswith("Tag: "):
                    print(line.split(": ", 1)[1])
                    raise SystemExit(0)

raise SystemExit("wheel tag not found")
PY
)

  FIXED_WHEEL="${TMP_DIR}/pydantic_core-${PYDANTIC_CORE_VERSION}-${WHEEL_TAG}.whl"
  cp "${ORIGINAL_WHEEL}" "${FIXED_WHEEL}"

  python -m pip install "${FIXED_WHEEL}"
  python -m pip install "pydantic==${PYDANTIC_VERSION}"
  python -m pip install -r requirements.txt

  python - <<'PY'
import pydantic
import pydantic_core

print(f"pydantic={pydantic.__version__}")
print(f"pydantic_core={pydantic_core.__version__}")
PY
}

cd "${PROJECT_DIR}"

if [ "${TERMUX_BOOTSTRAP_SKIP_PKG_UPDATE:-false}" != "true" ]; then
  pkg update -y
fi

ensure_termux_package python python
ensure_termux_package sqlite3 sqlite
ensure_termux_package git git
ensure_termux_package git-lfs git-lfs
ensure_termux_package curl curl
ensure_termux_package ssh openssh
ensure_termux_package termux-wake-lock termux-api

if command -v git-lfs >/dev/null 2>&1; then
  git lfs install --local
  git lfs pull
fi

mkdir -p data/logs

if ! install_python_deps; then
  printf 'ERROR python dependency bootstrap failed\n' >&2
  exit 1
fi

copy_bundled_bridge_apk() {
  apk_source="${PROJECT_DIR}/app-apk/kakao-bridge-app-debug.apk"
  download_dir="${TERMUX_DOWNLOAD_DIR:-${HOME}/storage/downloads}"
  apk_target="${download_dir}/kakao-bridge-app-debug.apk"

  if [ ! -f "${apk_source}" ]; then
    printf 'WARN bundled bridge APK missing: %s\n' "${apk_source}"
    return 0
  fi

  mkdir -p "${download_dir}"
  cp -f "${apk_source}" "${apk_target}"
  printf 'INFO copied bridge APK to downloads: %s\n' "${apk_target}"
}

copy_bundled_termux_installers() {
  download_dir="${TERMUX_DOWNLOAD_DIR:-${HOME}/storage/downloads}"
  source_dir="${PROJECT_DIR}/app-apk"

  if [ ! -d "${source_dir}" ]; then
    printf 'WARN bundled app-apk directory missing: %s\n' "${source_dir}"
    return 0
  fi

  mkdir -p "${download_dir}"

  for artifact in "${source_dir}"/com.termux_1022.z* "${source_dir}/com.termux_1022.zip" "${source_dir}/com.termux.api_1002.apk"; do
    if [ -f "${artifact}" ]; then
      cp -f "${artifact}" "${download_dir}/"
      printf 'INFO copied installer artifact to downloads: %s\n' "${artifact}"
    else
      printf 'WARN bundled installer artifact missing: %s\n' "${artifact}"
    fi
  done
}

copy_bundled_bridge_apk
copy_bundled_termux_installers

printf 'termux backend requirements ready: %s\n' "${PROJECT_DIR}"
