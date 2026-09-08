#!/usr/bin/env bash
# Boot the INSTALLED target disk on its own - no install medium
# attached (S7.1 Sections 29, 47). Proves the target is genuinely
# self-contained (its own ESP + root, never dependent on another
# disk's boot files). Requires qemu-system-x86_64.
#
# Usage: ./installer/scripts/boot-installed-target.sh <target-disk-qcow2> \
#          [--protected-disk PATH] [--ovmf-code PATH] [--result-json PATH]
#
# --protected-disk, if given, is attached too (present on the bus, but
# never the boot device and never written to by a boot-only path) so
# the "protected disk present + Serein target present -> Serein boots"
# acceptance scenario (Section 15) can be exercised in the same run;
# omit it entirely for the stronger "protected disk ABSENT + Serein
# target present -> Serein still boots" self-containment proof
# (Section 47).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "qemu-system-x86_64 is required for the installed-target boot check - not performed" >&2
    exit 1
fi

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <target-disk-qcow2> [--protected-disk PATH] [--ovmf-code PATH] [--result-json PATH]" >&2
    exit 1
fi

TARGET_DISK="$1"
shift

OVMF_CODE=""
RESULT_JSON=""
PY_ARGS=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --protected-disk) PY_ARGS+=(--extra-disk "$2"); shift 2 ;;
        --ovmf-code) OVMF_CODE="$2"; shift 2 ;;
        --result-json) RESULT_JSON="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

ACCEL="tcg"
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="kvm"
fi

# Deterministic OVMF firmware candidate rule (mirrors
# distribution/scripts/boot-smoke.sh's own rule).
if [ -z "${OVMF_CODE}" ]; then
    for candidate in \
        /usr/share/OVMF/OVMF_CODE_4M.fd \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/edk2/ovmf/OVMF_CODE.fd \
        /usr/share/qemu/OVMF_CODE.fd \
        ; do
        if [ -f "${candidate}" ]; then
            OVMF_CODE="${candidate}"
            break
        fi
    done
fi
if [ -n "${OVMF_CODE}" ]; then
    PY_ARGS+=(--ovmf-code "${OVMF_CODE}")
fi
if [ -n "${RESULT_JSON}" ]; then
    PY_ARGS+=(--result-json "${RESULT_JSON}")
fi

echo "==> Booting installed target ${TARGET_DISK} on its own (accel=${ACCEL})"
"${PYTHON_BIN}" -m serein.installer boot-check \
    --target-disk "${TARGET_DISK}" --accel "${ACCEL}" --require-uefi "${PY_ARGS[@]}"
