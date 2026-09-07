#!/usr/bin/env bash
# Safe cleanup of build intermediates (S7.0 Sections 73-75).
#
# Only ever deletes ${REPO_ROOT}/build (extraction/overlay/wheel work
# tree) - the verified upstream base cache under cache/upstream/ and any
# built ISO under dist/ are left alone by default (Section 75). Never
# trusts an arbitrary environment variable as the deletion target
# (Section 74's "safe delete invariant") - the target is always this
# script's own resolved REPO_ROOT/build path, verified to be a real
# descendant of the repository before anything is removed.
#
# Usage: ./distribution/scripts/clean.sh [--all]
#   --all   also remove cache/upstream/ (the cached base ISO) - asks
#           for explicit confirmation, since this forces a re-download.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build"

# Safe-delete invariant: resolve the target and re-derive it is really
# inside REPO_ROOT before deleting anything.
RESOLVED_BUILD_DIR="$(cd "${REPO_ROOT}" && python3 -c "
import sys
from pathlib import Path
root = Path('${REPO_ROOT}').resolve()
target = Path('${BUILD_DIR}').resolve()
if target != root / 'build':
    sys.exit(1)
print(target)
" 2>/dev/null || true)"

if [ -z "${RESOLVED_BUILD_DIR}" ]; then
    echo "Refusing to clean: resolved build directory did not match REPO_ROOT/build" >&2
    exit 1
fi

if [ -d "${RESOLVED_BUILD_DIR}" ]; then
    echo "==> Removing ${RESOLVED_BUILD_DIR}"
    rm -rf -- "${RESOLVED_BUILD_DIR}"
else
    echo "Nothing to clean under ${RESOLVED_BUILD_DIR}"
fi

if [ "${1:-}" = "--all" ]; then
    CACHE_DIR="${REPO_ROOT}/cache/upstream"
    read -r -p "Also remove verified base image cache at ${CACHE_DIR}? [y/N] " confirm
    if [ "${confirm}" = "y" ] || [ "${confirm}" = "Y" ]; then
        rm -rf -- "${CACHE_DIR}"
        echo "Removed ${CACHE_DIR}"
    fi
fi
