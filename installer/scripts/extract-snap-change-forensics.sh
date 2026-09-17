#!/usr/bin/env bash
# S7.1R12 Objectives C-G: bounded, host-side, read-only extraction of
# real snap Change/Task, snapd.hold, /snap/snapd/current, and desktop-
# portal forensic evidence from the real QEMU guest serial log.
#
# Architectural note (read before extending this script): this
# project's ONLY established, tested QA-install-medium mutation
# mechanism is boot-parameter patching of one GRUB menuentry
# (serein.installer.isoprep._add_kernel_token_to_qa_entry and its
# callers) - there is no squashfs-modification tooling anywhere in
# this repository or its CI dependencies (no unsquashfs/mksquashfs in
# .github/workflows/installer-smoke.yml's tool install list), so
# injecting a NEW live-session runtime sampler (a systemd
# service/timer that periodically runs `snap changes`/`snap tasks`/
# `systemctl show`/etc INSIDE the guest and reports back) is not
# achievable without a materially larger architecture change than a
# single corrective round justifies (Section 20's own "do not modify
# unrelated parts merely because they are nearby" principle). This
# script therefore extracts real Change/Task/portal/snapd.hold/
# snapd-current EVIDENCE FROM THE SAME raw serial log
# extract-bootstrap-milestones.sh already parses - real Run #12's own
# given evidence (systemd/snapd Change/Task failure text, xdg-desktop-
# portal activity) already appears on that console thanks to S7.1R5's
# `systemd.journald.forward_to_console=1` kernel-parameter fix, so no
# NEW guest-side instrumentation is required to surface it. This is
# NOT a live in-guest snapshot sampler (T0-T6 "checkpoints" below are
# raw-log timestamp ANCHORS, never a systemctl-show/journalctl live
# capture) - if/when a future round adds real squashfs-modification
# tooling, a genuine live sampler becomes possible and this script's
# scope can grow accordingly; until then, honestly reporting
# NOT_OBSERVED/BLOCKED for anything requiring live in-guest command
# execution is correct, never fabricated.
#
# Change IDs are NEVER hardcoded (real Run #12 used "Change 1", but
# nothing here assumes any specific ID) - discovered dynamically from
# whatever "Change <N>" references actually appear in the raw log.
#
# RAW_SERIAL_LOG=AUTHORITATIVE. This script's output is a
# NON_AUTHORITATIVE forensic convenience summary only, never a
# Layer-B gate - a missing serial log or zero matches both produce a
# valid, honest, empty-field output file, exactly like
# extract-bootstrap-milestones.sh's own established discipline.
#
# QA_ONLY / READ_ONLY / BOUNDED / NON_BLOCKING / FINITE / LOW_OVERHEAD
# / FAILURE_NON_FATAL (Section 11): this script only ever reads an
# already-captured host-side log file, never touches QEMU/the guest,
# never runs unbounded, and its own failure (missing log, zero
# matches) never fails the calling job - see the "Never fails the
# job" note at the bottom of this header.
#
# Usage: ./installer/scripts/extract-snap-change-forensics.sh <serial-log> <output-env-path>
#
# Never fails the job - a missing serial log or zero matches both
# produce a valid, honest output file.

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <serial-log> <output-path>" >&2
    exit 1
fi
SERIAL_LOG="$1"
OUTPUT="$2"

mkdir -p "$(dirname "${OUTPUT}")"

if [ ! -f "${SERIAL_LOG}" ]; then
    {
        echo "# no serial log present at ${SERIAL_LOG}"
    } > "${OUTPUT}"
    exit 0
fi

# Section 18 bounds - explicit, finite, documented. Truncation is
# always recorded, never silent.
MAX_CHANGE_IDS=20
MAX_SUMMARY_CHARS=200

_extract_timestamp() {
    grep -Eo '^[[:space:]]*\[?[[:space:]]*[0-9]+\.[0-9]+\]?' \
        | grep -Eo '[0-9]+\.[0-9]+' \
        | head -n1 || true
}

_first_valid_timestamp_for() {
    local pattern="$1"
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null | while IFS= read -r line; do
        ts="$(printf '%s\n' "${line}" | _extract_timestamp)"
        if [ -n "${ts}" ]; then
            printf '%s\n' "${ts}"
            break
        fi
    done || true
}

{
    echo "# S7.1R12 Objectives C-G - bounded, host-side,"
    echo "# NON_AUTHORITATIVE snap Change/Task, snapd.hold,"
    echo "# /snap/snapd/current, and desktop-portal forensic summary,"
    echo "# extracted from the real guest serial log (RAW_SERIAL_LOG is"
    echo "# always the authoritative source). Empty/absent means"
    echo "# NOT_OBSERVED in this run's serial log, never fabricated."
    echo "# See this script's own header for the architectural note on"
    echo "# why this is raw-log extraction, not a live in-guest"
    echo "# sampler."

    # -- Objective C/D: dynamic Change discovery + per-Change task
    # failure evidence. Never assumes "Change 1" - discovers whatever
    # real "Change <N>" references the raw log actually contains. --
    change_ids="$(
        grep -Eio -- 'Change [0-9]+' "${SERIAL_LOG}" 2>/dev/null \
            | grep -Eo '[0-9]+' \
            | sort -un \
            | head -n "${MAX_CHANGE_IDS}"
    )" || true
    change_count=0
    change_ids_truncated=0
    if [ -n "${change_ids}" ]; then
        total_distinct="$(printf '%s\n' "${change_ids}" | wc -l | tr -d ' ')"
        change_count="${total_distinct}"
        all_distinct="$(
            grep -Eio -- 'Change [0-9]+' "${SERIAL_LOG}" 2>/dev/null \
                | grep -Eo '[0-9]+' | sort -un | wc -l | tr -d ' '
        )" || true
        if [ -n "${all_distinct}" ] && [ "${all_distinct}" -gt "${MAX_CHANGE_IDS}" ]; then
            change_ids_truncated=1
        fi
    fi
    echo "change_ids=$(printf '%s' "${change_ids}" | tr '\n' ',' | sed 's/,$//')"
    echo "change_count=${change_count}"
    echo "change_ids_truncated=$([ "${change_ids_truncated}" -eq 1 ] && echo true || echo false)"

    # First-match-wins, set by the per-Change loop below.
    snapd_current_missing_change_id=""
    remove_snap_services_change_id=""

    # Per-Change extraction is a SINGLE grep + SINGLE awk pass per
    # Change ID (never multiple grep/while-read subshell chains) -
    # a real, measured performance requirement (Section 11
    # LOW_OVERHEAD): the original multi-pipeline-per-field
    # implementation took ~45s against just 29 discovered Change IDs
    # on this project's own Windows/MSYS2 development environment
    # (fork/exec-heavy, same class of overhead R10's milestone-script
    # correction already documented) - collapsing every per-Change
    # field (first/last failure timestamp, failure-line count, a
    # bounded/truncation-honest summary, and all topic-mention/
    # association flags) into ONE awk invocation removed the
    # per-matching-line subprocess fork entirely.
    if [ -n "${change_ids}" ]; then
        while IFS= read -r cid; do
            [ -n "${cid}" ] || continue

            # Order-independent by construction: any line containing
            # "Change <cid>" anywhere is grabbed regardless of where
            # in the line the topic/failure text itself sits.
            awk_out="$(
                grep -Ei -- "Change ${cid}\b" "${SERIAL_LOG}" 2>/dev/null | awk -v maxlen="${MAX_SUMMARY_CHARS}" '
                    {
                        line = $0
                        lower = tolower(line)
                        ts = ""
                        if (match(line, /\[[ \t]*[0-9]+\.[0-9]+\]/)) {
                            ts = substr(line, RSTART, RLENGTH)
                            gsub(/[^0-9.]/, "", ts)
                        } else if (match(line, /^[ \t]*[0-9]+\.[0-9]+/)) {
                            ts = substr(line, RSTART, RLENGTH)
                            gsub(/^[ \t]+/, "", ts)
                        }

                        if (index(lower, "desktop-security-center") > 0) mentions_desktop_security_center = 1
                        if (index(lower, "configure hook") > 0) mentions_configure_hook = 1
                        if (index(lower, "security profile setup") > 0) mentions_security_profile_setup = 1
                        if (index(lower, "removesnapservices") > 0) { mentions_removesnapservices = 1; assoc_remove_snap_services = 1 }
                        if (index(lower, "undo") > 0) mentions_undo = 1
                        if (index(lower, "rollback") > 0) mentions_rollback = 1
                        if (index(lower, "snapd/current") > 0) assoc_snapd_current = 1

                        is_failure = (index(lower, "fail") > 0 || index(lower, "error") > 0)
                        if (is_failure && ts != "") {
                            if (first_fail_ts == "") {
                                first_fail_ts = ts
                                summary = line
                                if (length(summary) > maxlen) {
                                    first_fail_summary = substr(summary, 1, maxlen)
                                    summary_truncated = 1
                                } else {
                                    first_fail_summary = summary
                                }
                            }
                            last_fail_ts = ts
                            fail_count++
                        }
                    }
                    END {
                        printf "first_fail_ts\t%s\n", first_fail_ts
                        printf "last_fail_ts\t%s\n", last_fail_ts
                        printf "fail_count\t%d\n", fail_count
                        printf "first_fail_summary\t%s\n", first_fail_summary
                        printf "summary_truncated\t%d\n", (summary_truncated ? 1 : 0)
                        printf "mentions_desktop_security_center\t%d\n", mentions_desktop_security_center
                        printf "mentions_configure_hook\t%d\n", mentions_configure_hook
                        printf "mentions_security_profile_setup\t%d\n", mentions_security_profile_setup
                        printf "mentions_removesnapservices\t%d\n", mentions_removesnapservices
                        printf "mentions_undo\t%d\n", mentions_undo
                        printf "mentions_rollback\t%d\n", mentions_rollback
                        printf "assoc_snapd_current\t%d\n", assoc_snapd_current
                        printf "assoc_remove_snap_services\t%d\n", assoc_remove_snap_services
                    }
                '
            )" || true

            first_fail_ts="" last_fail_ts="" fail_count=0 first_fail_summary="" summary_truncated=0
            mentions_desktop_security_center=0 mentions_configure_hook=0 mentions_security_profile_setup=0
            mentions_removesnapservices=0 mentions_undo=0 mentions_rollback=0
            assoc_snapd_current=0 assoc_remove_snap_services=0
            while IFS=$'\t' read -r field value; do
                case "${field}" in
                    first_fail_ts) first_fail_ts="${value}" ;;
                    last_fail_ts) last_fail_ts="${value}" ;;
                    fail_count) fail_count="${value}" ;;
                    first_fail_summary) first_fail_summary="${value}" ;;
                    summary_truncated) summary_truncated="${value}" ;;
                    mentions_desktop_security_center) mentions_desktop_security_center="${value}" ;;
                    mentions_configure_hook) mentions_configure_hook="${value}" ;;
                    mentions_security_profile_setup) mentions_security_profile_setup="${value}" ;;
                    mentions_removesnapservices) mentions_removesnapservices="${value}" ;;
                    mentions_undo) mentions_undo="${value}" ;;
                    mentions_rollback) mentions_rollback="${value}" ;;
                    assoc_snapd_current) assoc_snapd_current="${value}" ;;
                    assoc_remove_snap_services) assoc_remove_snap_services="${value}" ;;
                esac
            done <<< "${awk_out}"

            echo "change_${cid}_first_failure_timestamp=${first_fail_ts}"
            echo "change_${cid}_last_failure_timestamp=${last_fail_ts}"
            echo "change_${cid}_failure_line_count=${fail_count}"
            echo "change_${cid}_first_failure_summary=${first_fail_summary}"
            echo "change_${cid}_first_failure_summary_truncated=$([ "${summary_truncated}" = "1" ] && echo true || echo false)"
            echo "change_${cid}_mentions_desktop_security_center=$([ "${mentions_desktop_security_center}" = "1" ] && echo true || echo false)"
            echo "change_${cid}_mentions_configure_hook=$([ "${mentions_configure_hook}" = "1" ] && echo true || echo false)"
            echo "change_${cid}_mentions_security_profile_setup=$([ "${mentions_security_profile_setup}" = "1" ] && echo true || echo false)"
            echo "change_${cid}_mentions_removesnapservices=$([ "${mentions_removesnapservices}" = "1" ] && echo true || echo false)"
            echo "change_${cid}_mentions_undo=$([ "${mentions_undo}" = "1" ] && echo true || echo false)"
            echo "change_${cid}_mentions_rollback=$([ "${mentions_rollback}" = "1" ] && echo true || echo false)"

            # Section 6.1/Section 14/Objective G associations - stored
            # per-cid so the first matching cid wins the global
            # snapd_current_missing_associated_change_id/
            # remove_snap_services_associated_change_id fields below,
            # exactly like the previous implementation's own
            # first-match-wins discipline.
            if [ "${assoc_snapd_current}" = "1" ] && [ -z "${snapd_current_missing_change_id:-}" ]; then
                snapd_current_missing_change_id="${cid}"
            fi
            if [ "${assoc_remove_snap_services}" = "1" ] && [ -z "${remove_snap_services_change_id:-}" ]; then
                remove_snap_services_change_id="${cid}"
            fi
        done <<< "${change_ids}"
    fi

    # -- Objective F: snapd.hold forensics (facts only - never a
    # causal classification from this script itself; causality is a
    # human/report-level judgment, exactly like R11's
    # snapd_hold_finish precedent). --
    snapd_hold_start="$(_first_valid_timestamp_for 'Star(t|ted)(ing)? snapd\.hold')"
    snapd_hold_finish="$(_first_valid_timestamp_for 'Finished snapd\.hold')"
    echo "snapd_hold_start=${snapd_hold_start}"
    echo "snapd_hold_finish=${snapd_hold_finish}"

    # -- Objective G: /snap/snapd/current transition forensics. --
    snapd_current_missing_first="$(_first_valid_timestamp_for '/snap/snapd/current.*no such file or directory')"
    # A single awk pass counting only timestamped matches (never a
    # bare `grep -c`, which would also count a timestamp-less
    # duplicate rendering - see this script's shared discipline with
    # extract-bootstrap-milestones.sh's own
    # _remove_snap_services_event_count).
    snapd_current_missing_count="$(
        grep -Ei -- '/snap/snapd/current.*no such file or directory' "${SERIAL_LOG}" 2>/dev/null | awk '
            {
                ts = ""
                if (match($0, /\[[ \t]*[0-9]+\.[0-9]+\]/)) {
                    ts = "x"
                } else if (match($0, /^[ \t]*[0-9]+\.[0-9]+/)) {
                    ts = "x"
                }
                if (ts != "") count++
            }
            END { printf "%d\n", count }
        '
    )" || true
    echo "snapd_current_missing_first=${snapd_current_missing_first}"
    echo "snapd_current_missing_count=${snapd_current_missing_count}"
    # snapd_current_missing_change_id/remove_snap_services_change_id
    # are already computed (first-match-wins, bounded, order-
    # independent) by the per-Change awk pass above - never
    # recomputed here.
    echo "snapd_current_missing_associated_change_id=${snapd_current_missing_change_id}"
    echo "remove_snap_services_associated_change_id=${remove_snap_services_change_id}"

    # -- Objective E: desktop session / portal forensics, extracted
    # from the same raw log. This is source=raw_serial_log_only -
    # never a live systemctl/journalctl snapshot (see this script's
    # own header). If NONE of the portal-related patterns match
    # anywhere in the whole log, that is honest NOT_OBSERVED evidence
    # for this run, never a script failure. --
    portal_idle_monitor_timeout="$(_first_valid_timestamp_for 'idle monitor.*timeout|idle.*proxy.*timeout')"
    portal_desktop_request="$(_first_valid_timestamp_for 'org\.freedesktop\.portal\.Desktop')"
    portal_screencast_timeout="$(_first_valid_timestamp_for 'screencast.*[Pp]ortal.*[Tt]imeout|[Pp]ortal.*[Ss]ettings.*[Tt]imeout')"
    portal_xdg_desktop_portal_start="$(_first_valid_timestamp_for 'Star(t|ted)(ing)? xdg-desktop-portal\.service|Star(t|ted)(ing)? xdg-desktop-portal\b')"
    portal_xdg_desktop_portal_gnome_start="$(_first_valid_timestamp_for 'xdg-desktop-portal-gnome')"
    portal_xdg_desktop_portal_timeout="$(_first_valid_timestamp_for 'xdg-desktop-portal.*timeout|xdg-desktop-portal.*timed out')"
    portal_dbus_activation_timeout="$(_first_valid_timestamp_for '[Dd][Bb]us activation.*timeout|activation.*timeout.*[Dd][Bb]us')"

    echo "portal_idle_monitor_timeout=${portal_idle_monitor_timeout}"
    echo "portal_desktop_request=${portal_desktop_request}"
    echo "portal_screencast_timeout=${portal_screencast_timeout}"
    echo "portal_xdg_desktop_portal_start=${portal_xdg_desktop_portal_start}"
    echo "portal_xdg_desktop_portal_gnome_start=${portal_xdg_desktop_portal_gnome_start}"
    echo "portal_xdg_desktop_portal_timeout=${portal_xdg_desktop_portal_timeout}"
    echo "portal_dbus_activation_timeout=${portal_dbus_activation_timeout}"

    portal_any_observed=false
    for v in "${portal_idle_monitor_timeout}" "${portal_desktop_request}" \
             "${portal_screencast_timeout}" "${portal_xdg_desktop_portal_start}" \
             "${portal_xdg_desktop_portal_gnome_start}" "${portal_xdg_desktop_portal_timeout}" \
             "${portal_dbus_activation_timeout}"; do
        [ -n "${v}" ] && portal_any_observed=true
    done
    echo "portal_forensics_source=raw_serial_log_only"
    echo "portal_forensics_status=$([ "${portal_any_observed}" = "true" ] && echo OBSERVED || echo NOT_OBSERVED)"
    echo "portal_live_state_snapshot_supported=false"
} > "${OUTPUT}"
