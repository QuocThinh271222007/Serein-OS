#!/usr/bin/env bash
# The single canonical Serein ISO build entrypoint (S7.0 Section 13).
# Thin wrapper around `python -m serein.distribution build` - see
# src/serein/distribution/build.py for the actual pipeline. Refuses to
# proceed if the base image has not already been fetched+verified.
#
# Usage: ./distribution/scripts/build-iso.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if ! command -v xorriso >/dev/null 2>&1; then
    echo "xorriso is required to build the ISO - see docs/distribution/iso-build.md" >&2
    exit 1
fi

echo "==> Verifying base image before build (fail-closed)"
"${PYTHON_BIN}" -m serein.distribution verify-base

SOURCE_COMMIT="$(git rev-parse HEAD)"
echo "==> Building Serein Alpha ISO from commit ${SOURCE_COMMIT}"
"${PYTHON_BIN}" -m serein.distribution build --source-commit "${SOURCE_COMMIT}"
