#!/usr/bin/env bash
# One command for local S0 validation: tests, lint, and type checks.
# Mirrors what CI runs (.github/workflows/ci.yml). Read-only; requires no
# root and makes no network calls beyond what pip already needed at
# dev-bootstrap time.
#
# Usage: ./scripts/verify.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

echo "==> pytest"
"${PYTHON_BIN}" -m pytest

echo "==> ruff check"
"${PYTHON_BIN}" -m ruff check src tests

echo "==> mypy"
"${PYTHON_BIN}" -m mypy

echo
echo "All S0 checks passed."
