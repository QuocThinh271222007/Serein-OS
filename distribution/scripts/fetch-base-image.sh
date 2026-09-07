#!/usr/bin/env bash
# Explicit, deliberate download of the pinned upstream Ubuntu base image
# (S7.0 Section 12). Never run by pytest/ruff/mypy/verify.sh - this is
# the ONLY place in the repository a multi-GB network download happens,
# and it only happens when a human or CI job runs this script on
# purpose.
#
# Usage: ./distribution/scripts/fetch-base-image.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE_DIR="${REPO_ROOT}/cache/upstream"
BASE_IMAGE_JSON="${REPO_ROOT}/distribution/base-image.json"

if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required to read distribution/base-image.json" >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to fetch the base image" >&2
    exit 1
fi

FILENAME="$(jq -r '.filename' "${BASE_IMAGE_JSON}")"
DOWNLOAD_URL="$(jq -r '.download_url' "${BASE_IMAGE_JSON}")"

if [ "${DOWNLOAD_URL}" = "null" ] || [ -z "${DOWNLOAD_URL}" ]; then
    echo "distribution/base-image.json has no download_url pinned" >&2
    exit 1
fi

mkdir -p "${CACHE_DIR}"
DEST="${CACHE_DIR}/${FILENAME}"

# Space check: refuse to start a multi-GB download without headroom
# (Section 72). 8 GiB is a conservative floor for a ~6 GB Desktop ISO.
AVAILABLE_KB="$(df -Pk "${CACHE_DIR}" | tail -1 | awk '{print $4}')"
REQUIRED_KB=$((8 * 1024 * 1024))
if [ "${AVAILABLE_KB}" -lt "${REQUIRED_KB}" ]; then
    echo "Insufficient disk space under ${CACHE_DIR}: ${AVAILABLE_KB} KiB available, ${REQUIRED_KB} KiB required" >&2
    exit 1
fi

echo "==> Fetching ${DOWNLOAD_URL}"
echo "    -> ${DEST}"
curl -fL --continue-at - -o "${DEST}" "${DOWNLOAD_URL}"

echo "==> Fetching SHA256SUMS / SHA256SUMS.gpg alongside it"
SHA_URL="$(jq -r '.sha256sums_url' "${BASE_IMAGE_JSON}")"
SIG_URL="$(jq -r '.signature_url' "${BASE_IMAGE_JSON}")"
curl -fsSL -o "${CACHE_DIR}/SHA256SUMS" "${SHA_URL}"
curl -fsSL -o "${CACHE_DIR}/SHA256SUMS.gpg" "${SIG_URL}"

echo "Download complete. Run ./distribution/scripts/verify-base-image.sh before building."
