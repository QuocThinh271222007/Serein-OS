#!/usr/bin/env bash
# Prepare a local development environment for Serein OS.
#
# Creates a virtual environment inside the repository checkout and installs
# the project in editable mode with development dependencies. Never touches
# anything outside the checkout and never requires root.
#
# Usage: ./scripts/dev-bootstrap.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

if [ "$(id -u 2>/dev/null || echo 1000)" = "0" ]; then
    echo "error: do not run dev-bootstrap.sh as root." >&2
    exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment at ${VENV_DIR}"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

if [ -f "${VENV_DIR}/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    VENV_PYTHON="${VENV_DIR}/bin/python"
else
    # Windows-style venv layout (Git Bash on Windows).
    # shellcheck disable=SC1091
    source "${VENV_DIR}/Scripts/activate"
    VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
fi

echo "Installing serein in editable mode with dev dependencies"
"${VENV_PYTHON}" -m pip install --upgrade pip >/dev/null
"${VENV_PYTHON}" -m pip install -e "${REPO_ROOT}[dev]"

echo
echo "Done. Activate the environment with:"
echo "  source ${VENV_DIR}/bin/activate   (Linux/macOS)"
echo "  source ${VENV_DIR}/Scripts/activate   (Windows/Git Bash)"
echo "Then run: serein version"
