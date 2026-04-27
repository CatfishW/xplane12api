#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/your-user/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

REPO_ROOT="${REPO_ROOT:-/home/your-user/Development}"
XPLANE_HOME="${XPLANE_HOME:-/home/your-user/X-Plane 12}"
PLUGIN_NAME="${XPLANE_PLUGIN_NAME:-XPlane12ImageBridge}"
PLUGIN_SOURCE_DIR="${REPO_ROOT}/xplane12/plugin"
PLUGIN_BUILD_DIR="${PLUGIN_SOURCE_DIR}/build"
PLUGIN_OUTPUT="${PLUGIN_BUILD_DIR}/${PLUGIN_NAME}.xpl"
PLUGIN_ROOT_DIR="${XPLANE_HOME}/Resources/plugins/${PLUGIN_NAME}"
PLUGIN_INSTALL_DIR="${PLUGIN_ROOT_DIR}/64"
PLUGIN_INSTALL_PATH="${PLUGIN_INSTALL_DIR}/lin.xpl"
LEGACY_PLUGIN_DIR="${PLUGIN_ROOT_DIR}/lin_x64"
IMAGE_EXPORT_DIR="${XPLANE_IMAGE_EXPORT_DIR:-${REPO_ROOT}/.runtime/xplane12_images}"

if [[ ! -f "${PLUGIN_SOURCE_DIR}/CMakeLists.txt" ]]; then
    echo "[xplane12_plugin_sync] missing plugin source at ${PLUGIN_SOURCE_DIR}" >&2
    exit 1
fi

mkdir -p "${PLUGIN_BUILD_DIR}" "${PLUGIN_INSTALL_DIR}" "${IMAGE_EXPORT_DIR}"

cmake -S "${PLUGIN_SOURCE_DIR}" -B "${PLUGIN_BUILD_DIR}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${PLUGIN_BUILD_DIR}" --config Release -j"$(nproc)"

if [[ ! -f "${PLUGIN_OUTPUT}" ]]; then
    echo "[xplane12_plugin_sync] build did not produce ${PLUGIN_OUTPUT}" >&2
    exit 1
fi

install -m 0755 "${PLUGIN_OUTPUT}" "${PLUGIN_INSTALL_PATH}"
if [[ -d "${LEGACY_PLUGIN_DIR}" ]]; then
    rm -rf "${LEGACY_PLUGIN_DIR}"
fi
echo "[xplane12_plugin_sync] installed ${PLUGIN_INSTALL_PATH}"
