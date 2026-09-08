#!/usr/bin/env bash
# Boot the QA-install ISO (real autoinstall.yaml embedded by
# `python -m serein.installer prepare-qa-install-iso` - S7.1 Section
# 42-43) against the two fixture disks and let the real installer run
# to completion. NEVER a physical disk (Section 49-50) - both drives
# here are qcow2 FILES this workflow already created via
# create-fixture-disks.sh.
#
# Explicit, fixed serials are assigned to each virtual disk
# (SEREIN-TARGET-DISK / SEREIN-PROTECTED-DISK) so the rendered
# autoinstall.yaml's storage `match` stanza
# (serein.installer.renderer.render_autoinstall_storage_config) can
# reference the target deterministically - the in-guest analog of
# Section 11's "prefer stable evidence" for a virtual disk that has no
# real hardware serial of its own.
#
# Usage: ./installer/scripts/run-qa-install.sh <qa-install-iso> \
#          <protected-disk-qcow2> <target-disk-qcow2> \
#          [--ovmf-code PATH] [--timeout SECONDS]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <qa-install-iso> <protected-disk> <target-disk>" \
         "[--ovmf-code PATH] [--timeout SECONDS]" >&2
    exit 1
fi
ISO="$1"; PROTECTED_DISK="$2"; TARGET_DISK="$3"
shift 3

OVMF_CODE=""
TIMEOUT_SECONDS=1800
while [ "$#" -gt 0 ]; do
    case "$1" in
        --ovmf-code) OVMF_CODE="$2"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

# Deterministic OVMF firmware candidate rule (mirrors
# distribution/scripts/boot-smoke.sh's own rule - Section 46 of the
# S7.0R corrective) - never "whatever find happens to return first".
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
if [ -z "${OVMF_CODE}" ]; then
    echo "::error::no OVMF firmware found - S7.1 closure requires real UEFI evidence" >&2
    exit 1
fi

ACCEL="tcg"
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="kvm"
fi

SERIAL_LOG="$(dirname "${TARGET_DISK}")/qa-install-serial.log"

echo "==> Running real QA autoinstall (accel=${ACCEL}, timeout=${TIMEOUT_SECONDS}s)"
echo "    protected disk: ${PROTECTED_DISK} (must remain byte-identical)"
echo "    target disk:     ${TARGET_DISK} (will be destructively repartitioned)"

# -no-reboot: a well-formed autoinstall run powers the guest off itself
# once curtin/late-commands finish (Subiquity's own shutdown behavior),
# which ends qemu; the outer `timeout` is the fail-closed backstop if
# that never happens - never an unbounded wait.
set +e
timeout --signal=TERM "${TIMEOUT_SECONDS}" qemu-system-x86_64 \
    -m 4096 -smp 2 -accel "${ACCEL}" \
    -drive if=pflash,format=raw,readonly=on,file="${OVMF_CODE}" \
    -cdrom "${ISO}" \
    -drive if=virtio,format=qcow2,file="${PROTECTED_DISK}",serial=SEREIN-PROTECTED-DISK \
    -drive if=virtio,format=qcow2,file="${TARGET_DISK}",serial=SEREIN-TARGET-DISK \
    -boot d \
    -display none -no-reboot \
    -serial "file:${SERIAL_LOG}"
STATUS=$?
set -e

if [ "${STATUS}" -ne 0 ]; then
    echo "::error::QA autoinstall QEMU run exited non-zero or timed out (status=${STATUS})" >&2
    echo "--- serial log tail ---" >&2
    tail -n 200 "${SERIAL_LOG}" >&2 2>/dev/null || true
    exit 1
fi

echo "PASS: QA autoinstall run completed (QEMU exited cleanly)"
