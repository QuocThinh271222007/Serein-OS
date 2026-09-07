#!/usr/bin/env bash
# Automated QEMU boot-smoke validation (S7.0 Sections 45-49, 92).
# No target disk is ever attached; the run is bounded by a finite
# timeout and reports positive/negative evidence, never "the process
# stayed alive". Requires qemu-system-x86_64 - not installed in every
# environment, and never required by normal unit-test CI (Section 49).
#
# Usage: ./distribution/scripts/boot-smoke.sh <path-to-iso> [--ovmf-code PATH]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "qemu-system-x86_64 is required for boot-smoke validation - not performed" >&2
    exit 1
fi

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <path-to-iso> [--ovmf-code PATH]" >&2
    exit 1
fi

ISO_PATH="$1"
shift

ACCEL="tcg"
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="kvm"
fi

echo "==> Boot-smoke validating ${ISO_PATH} (accel=${ACCEL})"
"${PYTHON_BIN}" -m serein.distribution boot-smoke --iso "${ISO_PATH}" --accel "${ACCEL}" "$@"
