#!/usr/bin/env bash
# Read-only structural inspection of a built ISO or extracted tree
# (S7.0 Section 52). Never mounts the medium.
#
# Usage: ./distribution/scripts/inspect-iso.sh <path-to-iso-or-tree>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path-to-iso-or-extracted-tree>" >&2
    exit 1
fi

"${PYTHON_BIN}" -m serein.distribution inspect "$1"
