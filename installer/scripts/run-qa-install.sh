#!/usr/bin/env bash
# Boot the QA-install ISO (real autoinstall.yaml embedded by
# `python -m serein.installer prepare-qa-install-iso` - S7.1 Section
# 42-43) against the two fixture disks and let the real installer run
# to completion. NEVER a physical disk (Section 49-50) - both drives
# here are qcow2 FILES this workflow already created via
# create-fixture-disks.sh.
#
# S7.1R2 Corrective A (real Installer Layer-B run #2,
# RUN_ID=34219273003, failed at install_failed): the drives are
# attached via the modern split backend/device form
# (`-drive if=none,id=...` + `-device virtio-blk-pci,...,serial=...`),
# never the legacy `-drive if=virtio,...,serial=...` convenience
# shorthand, which is a known compatibility hazard on current QEMU -
# the shorthand does not reliably plumb `serial=` through to the
# device model on every QEMU version. Each backend/device pair has an
# explicit, deterministic id (never a QEMU-generated one), so the
# protected and target serials can never be silently swapped.
#
# Explicit, fixed serials are still assigned to each virtual disk
# (SEREIN-PROTECTED-DISK / SEREIN-TARGET-DISK) so the rendered
# autoinstall.yaml's storage `match` stanza
# (serein.installer.renderer.render_autoinstall_storage_config) can
# reference the target deterministically - the in-guest analog of
# Section 11's "prefer stable evidence" for a virtual disk that has no
# real hardware serial of its own. Never `/dev/vdX` ordinal selection,
# never "largest disk", never "first disk", never physical passthrough.
#
# S7.1R2 Corrective B: a bounded, non-destructive QEMU startup probe
# (`-S`, frozen CPU) runs BEFORE the real timed install, proving the
# full command line/device model is syntactically and semantically
# valid without waiting up to the full install timeout. A probe
# failure is real evidence of a `qemu_startup` defect and is reported
# immediately - it is never treated as installer success or failure in
# its own right ("QEMU invocation valid != installer PASS" - Section
# 6). QEMU's own stdout/stderr are ALWAYS captured to a dedicated
# diagnostic log (never only the guest `-serial` log, which may not
# even exist if QEMU dies during command-line parsing), and a bounded
# tail is ever printed to the job console - the full file is retained
# as a workflow artifact.
#
# Usage: ./installer/scripts/run-qa-install.sh <qa-install-iso> \
#          <protected-disk-qcow2> <target-disk-qcow2> \
#          [--ovmf-code PATH] [--timeout SECONDS]
#
# On every exit path (probe failure, real-run failure, or success) this
# script writes a small `key=value` result file next to the target
# disk (`qa-install-qemu-result.env`) suitable for
# `cat ... >> "$GITHUB_OUTPUT"` - see Section 7's required evidence
# fields, each documented at the point they are computed below.

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
# S7.1R6 Objective A: default kept in sync with the real workflow's
# own explicit --timeout 5400 - only matters for a manual/local
# invocation without --timeout; real Run #6 proved 1800s was too
# tight (curtin was actively progressing at ~1769s), and real Run #8
# then proved 3600s was ALSO too tight (curtin was actively
# progressing through curthooks/EFI/kernel-package install right up
# to the deadline).
#
# S7.1R9 Objective D: real Run #9 reached curthooks completion
# (~5049.98s) and unattended-upgrades starting (~5320.23s) - only
# ~80s of margin remained at the 5400s deadline. Kept at 5400s this
# pass rather than increased further: Run #9 also exposed a real,
# pathological firmware-notifier restart storm running concurrently
# with curthooks/postinstall, now neutralized QA-side-only
# (serein.installer.isoprep._mask_firmware_notifier_on_qa_entry) - see
# the workflow's own "Run real QA autoinstall" step comment for the
# full rationale. Not a claim 5400s is proven sufficient; Run #10 is
# the real test.
TIMEOUT_SECONDS=5400
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

WORK_DIR="$(dirname "${TARGET_DISK}")"
SERIAL_LOG="${WORK_DIR}/qa-install-serial.log"
QEMU_STDOUT_LOG="${WORK_DIR}/qa-install-qemu-stdout.log"
QEMU_STDERR_LOG="${WORK_DIR}/qa-install-qemu-stderr.log"
RESULT_ENV="${WORK_DIR}/qa-install-qemu-result.env"

# Overridable only for fast, real, sub-second test execution
# (tests/test_installer.py::TestRunQaInstallScript) - production always
# uses the real defaults.
PROBE_TIMEOUT_SECONDS="${SEREIN_TEST_PROBE_TIMEOUT_SECONDS:-8}"
RUN_STARTED_GRACE_SECONDS="${SEREIN_TEST_RUN_STARTED_GRACE_SECONDS:-2}"

# S7.1R2 Corrective A/Section 5: explicit backend/device split, one
# deterministic id per pair, never a QEMU-generated id, never possible
# to swap protected<->target serials by construction (each serial is
# hardcoded onto its own named device, never derived positionally).
#
# S7.1R4 Corrective A: the protected backend is now attached
# `readonly=on` (real Run #4, RUN_ID=34239853849, proved the protected
# qcow2's CONTAINER hash changed for the second consecutive real run,
# while the target's did not - and this line, without `readonly=on`,
# is the exact point QEMU opens the protected image for write access,
# in BOTH the bounded startup probe below and the real timed run).
# `readonly=on` closes off every QEMU-side write vector categorically
# (guest-triggered writes, qcow2's own internal lazy-refcount/dirty-bit
# bookkeeping on open/close) - never merely inferred to help, but a
# real, structural QEMU block-layer guarantee. This is independently,
# architecturally correct regardless of root cause: a disk that exists
# ONLY to prove the installer will never touch it should never be
# opened for write access by ANY component in the first place -
# defense-in-depth, not merely a hash-greening trick. Read-only access
# remains fully sufficient for the guest to discover, identify by
# serial, and correctly reject this disk as non-target (no component
# needs write access merely to probe/enumerate a disk).
QEMU_ARGS=(
    -m 4096 -smp 2 -accel "${ACCEL}"
    -drive if=pflash,format=raw,readonly=on,file="${OVMF_CODE}"
    -drive if=none,id=serein_protected_backend,format=qcow2,file="${PROTECTED_DISK}",readonly=on
    -device virtio-blk-pci,id=serein_protected_device,drive=serein_protected_backend,serial=SEREIN-PROTECTED-DISK
    -drive if=none,id=serein_target_backend,format=qcow2,file="${TARGET_DISK}"
    -device virtio-blk-pci,id=serein_target_device,drive=serein_target_backend,serial=SEREIN-TARGET-DISK
    -cdrom "${ISO}"
    -boot d
    -display none -no-reboot
)

echo "==> Running real QA autoinstall (accel=${ACCEL}, timeout=${TIMEOUT_SECONDS}s)"
echo "    protected disk: ${PROTECTED_DISK} (must remain byte-identical, serial=SEREIN-PROTECTED-DISK)"
echo "    target disk:     ${TARGET_DISK} (will be destructively repartitioned, serial=SEREIN-TARGET-DISK)"

# _userspace_reached <log-path> - a WEAK, diagnostic-only heuristic
# (Section 11) that the guest kernel/init got as far as producing
# console output - NEVER used for real closure evidence (Section 20's
# "no weak markers" rule applies only to the INSTALLED-system boot
# check's closure marker, not this bounded, honestly-labelled
# diagnostic fact).
_userspace_reached() {
    local log="$1"
    if [ -f "${log}" ] && grep -Eq \
        'Linux version|Booting Linux|cloud-init|Subiquity|systemd\[1\]|login:' \
        "${log}" 2>/dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

# _write_result <exit-status> <failure-stage> <qemu-started> <elapsed-seconds>
# Always writes the full required evidence field set (Section 7),
# regardless of which exit path got here - `failure_stage` is empty on
# a real pass. `serial_log_present` is computed fresh each time so a
# QEMU death before the guest ever opens its serial console is
# reported honestly (Section 8) rather than silently missing.
_write_result() {
    local status="$1" stage="$2" started="$3" elapsed="$4"
    local serial_present="false"
    [ -f "${SERIAL_LOG}" ] && serial_present="true"
    local userspace
    userspace="$(_userspace_reached "${SERIAL_LOG}")"
    cat > "${RESULT_ENV}" <<EOF
qemu_exit_status=${status}
qemu_accelerator=${ACCEL}
qemu_firmware=${OVMF_CODE}
qemu_timeout_seconds=${TIMEOUT_SECONDS}
qemu_serial_log_path=${SERIAL_LOG}
qemu_diagnostic_log_path=${QEMU_STDERR_LOG}
qemu_started=${started}
qemu_elapsed_seconds=${elapsed}
failure_stage=${stage}
installer_userspace_reached=${userspace}
serial_log_present=${serial_present}
EOF
}

_print_diagnostic_tail() {
    if [ -f "${SERIAL_LOG}" ]; then
        echo "--- serial log tail ---" >&2
        tail -n 200 "${SERIAL_LOG}" >&2 2>/dev/null || true
    fi
    if [ -s "${QEMU_STDERR_LOG}" ]; then
        echo "--- qemu stderr tail ---" >&2
        tail -n 200 "${QEMU_STDERR_LOG}" >&2 2>/dev/null || true
    fi
}

# --- Corrective B: bounded, non-destructive QEMU startup probe -------
#
# The EXACT same command line the real run below uses, with `-S`
# appended (freeze CPU at startup - no guest code ever runs) and
# reusing the real serial/diagnostic log paths. A syntactically and
# semantically valid invocation stays alive (frozen) for the whole
# probe window; an invalid one (bad flag, unsupported device property,
# backend/device mismatch) exits immediately with a real, captured
# diagnostic. This can NEVER become installer success on its own -
# only a real, unfrozen run below can pass.
echo "==> Probing QEMU command-line/device-model validity (bounded, ${PROBE_TIMEOUT_SECONDS}s, non-destructive)"
set +e
qemu-system-x86_64 "${QEMU_ARGS[@]}" -serial "file:${SERIAL_LOG}" -S \
    >"${QEMU_STDOUT_LOG}" 2>"${QEMU_STDERR_LOG}" &
PROBE_PID=$!
PROBE_WAITED=0
while [ "${PROBE_WAITED}" -lt "${PROBE_TIMEOUT_SECONDS}" ]; do
    if ! kill -0 "${PROBE_PID}" 2>/dev/null; then
        break
    fi
    sleep 1
    PROBE_WAITED=$((PROBE_WAITED + 1))
done
if kill -0 "${PROBE_PID}" 2>/dev/null; then
    # Still alive after the full probe window - QEMU accepted the
    # command line and constructed every backend/device. Frozen the
    # entire time; never ran any guest code. Kill it now.
    kill "${PROBE_PID}" 2>/dev/null || true
    wait "${PROBE_PID}" 2>/dev/null
    PROBE_STATUS=0
else
    wait "${PROBE_PID}"
    PROBE_STATUS=$?
fi
set -e

if [ "${PROBE_STATUS}" -ne 0 ]; then
    echo "::error::QEMU startup probe failed (status=${PROBE_STATUS}) - invalid command line" \
         "or device model, never reached the real install" >&2
    _print_diagnostic_tail
    _write_result "${PROBE_STATUS}" "qemu_startup" "false" "${PROBE_WAITED}"
    exit 1
fi
echo "PASS: QEMU startup probe accepted the command line - proceeding to the real install"

# --- The real, timed install run --------------------------------------
#
# -no-reboot: a well-formed autoinstall run powers the guest off itself
# once curtin/late-commands finish (Subiquity's own shutdown behavior),
# which ends qemu; the outer `timeout` is the fail-closed backstop if
# that never happens - never an unbounded wait. QEMU's own stdout/
# stderr are captured independently of the guest `-serial` log
# (Section 8) - the probe already proved the command line is valid, so
# a real-run failure here is never a `qemu_startup` defect.
START_TIME=$(date +%s)
set +e
timeout --signal=TERM "${TIMEOUT_SECONDS}" qemu-system-x86_64 "${QEMU_ARGS[@]}" \
    -serial "file:${SERIAL_LOG}" \
    >"${QEMU_STDOUT_LOG}" 2>"${QEMU_STDERR_LOG}" &
RUN_PID=$!
sleep "${RUN_STARTED_GRACE_SECONDS}"
QEMU_STARTED="false"
if kill -0 "${RUN_PID}" 2>/dev/null; then
    QEMU_STARTED="true"
fi
wait "${RUN_PID}"
STATUS=$?
set -e
END_TIME=$(date +%s)
ELAPSED_SECONDS=$((END_TIME - START_TIME))

if [ "${STATUS}" -eq 0 ]; then
    _write_result 0 "" "${QEMU_STARTED}" "${ELAPSED_SECONDS}"
    echo "PASS: QA autoinstall run completed (QEMU exited cleanly)"
    exit 0
fi

_print_diagnostic_tail

if [ "${STATUS}" -eq 124 ] || [ "${STATUS}" -eq 137 ]; then
    # 124: `timeout` itself killed the process via SIGTERM; 137: it
    # escalated to SIGKILL - either way this is a bounded-timeout
    # failure, never conflated with a real installer-execution defect.
    echo "::error::QA autoinstall QEMU run timed out after ${TIMEOUT_SECONDS}s (status=${STATUS})" >&2
    _write_result "${STATUS}" "installer_timeout" "${QEMU_STARTED}" "${ELAPSED_SECONDS}"
    exit 1
fi

if [ "${QEMU_STARTED}" != "true" ]; then
    # Should not normally happen once the probe above already passed -
    # captured anyway as an honest `qemu_startup` classification rather
    # than silently folding it into installer_execution.
    echo "::error::QEMU exited before the real run was observed to start (status=${STATUS})" >&2
    _write_result "${STATUS}" "qemu_startup" "false" "${ELAPSED_SECONDS}"
    exit 1
fi

echo "::error::QA autoinstall QEMU run exited non-zero (status=${STATUS}) - QEMU started" \
     "successfully (probe passed, process ran ${ELAPSED_SECONDS}s) but the real installer failed" >&2
_write_result "${STATUS}" "installer_execution" "true" "${ELAPSED_SECONDS}"
exit 1
