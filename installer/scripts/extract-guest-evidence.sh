#!/usr/bin/env bash
# S7.1R14 Objective A / S7.1R15 Objective B: bounded, host-side,
# read-only extraction of the QA-only guest evidence channel into a
# compact summary + per-item artifact files.
#
# `run-qa-install.sh`'s QEMU_ARGS wire a dedicated virtio-serial port
# (org.serein.qa.evidence) backed by a `-chardev file,...` sink
# (qa-install-guest-evidence.log) - a real, structurally one-way QEMU
# backend the guest may only WRITE into (see run-qa-install.sh's own
# QEMU_ARGS comment for the full safety rationale). S7.1R19: a short-
# lived launcher (serein.installer.renderer.build_qa_evidence_launcher_script,
# embedded via a base64-encoded Subiquity early-commands directive -
# see render_autoinstall_yaml's own docstring for why this replaced an
# earlier `systemd.run=` kernel-token mechanism) hands the long-running
# watcher (build_qa_evidence_watcher_script) off to an independent
# `systemd-run --no-block --collect` transient unit. Both the launcher
# and the watcher write bounded markers/blocks to this sink:
#
#   SEREIN_EVIDENCE_LAUNCHER_STARTED / launcher_start_ts=
#   SEREIN_EVIDENCE_LAUNCHER_COMPLETED / launcher_finish_ts=
#       one-time boot markers (S7.1R17/R19) bracketing the launcher's
#       own `systemd-run` handoff call - the guest's own monotonic
#       timestamps proving (or disproving) that the launcher actually
#       ran and completed quickly, rather than merely asserting the
#       mechanism exists.
#   SEREIN_EVIDENCE_WATCHER_STARTED / watcher_start_monotonic_ts=
#       a one-time boot marker (S7.1R16 Objective A/8) - the guest's
#       own monotonic timestamp at the moment the watcher started,
#       proving (or disproving) that it actually started before the
#       first snap failure, rather than merely asserting the mechanism
#       exists.
#   ===BEGIN-CRASH-EVIDENCE===/===END-CRASH-EVIDENCE===
#       whenever it observes a new /var/crash/*block_probe_fail*.crash
#       file (S7.1R14 - the block-probe pathology). S7.1R21 Section
#       14: a crash FILE existing is never conflated with its content
#       being CAPTURED - the frame's own `size=` field (already
#       present since S7.1R14) is now surfaced as an explicit summary
#       distinction (see guest_evidence_crash_block_nonempty_count
#       below) - a real S7.1R20 crash file was 0 bytes.
#   === SEREIN SNAP FAILURE FRAME ===/=== END FRAME ===
#       whenever it observes one of the recurring snap/bootstrap
#       pathology signals (S7.1R15/R16 - a snapd.service start
#       timeout, desktop-security-center hook failure, sanity timeout,
#       RemoveSnapServices, a missing /snap/snapd/current, or a
#       snapd.seeded failure) - now including the actual failed snap
#       Change task graph, snapd.service state/journal context, and
#       explicit ordering timestamps (S7.1R16 Objectives B-G).
#   === SEREIN STORAGE PROBE FRAME ===/=== END STORAGE PROBE FRAME ===
#       S7.1R21: whenever it observes the first occurrence of one of
#       three known Filesystem/_probe/probe_once storage-probe
#       failure signals (probe_once+cancelled, block_probe_fail,
#       disk_probe_fail - the real S7.1R20 forensic findings) -
#       bounded, allowlisted installer-log excerpts, read-only device
#       topology/identity, a process snapshot, a storage-filtered
#       journal window, and a dedicated udisks2 context section
#       (observation only - see build_qa_evidence_watcher_script's own
#       docstring for the complete guest-side contract). S7.1R22: each
#       frame now also carries `trigger_source=` (journal_cursor,
#       bounded_window_fallback, or crash_file - HOW the trigger fired,
#       never guessed) and `trigger_event_timestamp=` (the matched
#       journal line's own monotonic timestamp, or NOT_OBSERVED for a
#       crash_file trigger - never fabricated from the frame's own,
#       separate, `frame_capture_timestamp=`/`timestamp=` field). Real
#       S7.1R21-TCG-REPRO-1 evidence proved the shared 200-line
#       snap-signal journal snapshot this frame kind's DETECTION
#       (never its own separate, wider CONTENT fetch, already
#       unaffected) previously reused is unreliable under high journal
#       volume - see build_qa_evidence_watcher_script's own docstring
#       for the full corrective. An OLD-format frame (no
#       trigger_source=/trigger_event_timestamp= lines) parses fine
#       here - those two fields simply read NOT_OBSERVED, never a
#       parser failure.
#
# Run #17 (or any future run) may reproduce ANY of these pathology
# families, all, or none - this script handles every combination and
# always produces a valid, honest output (S7.1R15 Section 22).
# Ordering fields (e.g. snapd_failure_precedes_portal_failure) are
# computed from the EARLIEST value each timestamp ever took across
# every parsed frame, and read "unknown" - never guessed - whenever
# either side was never observed in this run's own bounded journal
# windows.
#
# This script turns that raw text into:
#
#   <output-env>                                          - summary
#   <crash-output-dir>/qa-install-block-probe-crash-N.txt - bounded
#       per-crash artifacts (block-probe pathology)
#   <crash-output-dir>/qa-install-snap-failure-frame-N.txt - bounded
#       per-frame artifacts (snap/bootstrap pathology)
#   <crash-output-dir>/qa-install-storage-probe-frame-N.txt - bounded
#       per-frame artifacts (S7.1R21 storage-probe instrumentation)
#
# Never fails the job - a missing/empty guest-evidence log, or
# malformed/unparseable block content, all produce a valid, honest
# output rather than a non-zero exit (matches every other extractor
# script in this directory - RAW_SERIAL_LOG/RAW_GUEST_EVIDENCE_LOG
# remain the authoritative source; this is a non-authoritative,
# read-only forensic convenience only).
#
# S7.1R15 Section 16: real Run #15 exposed a genuine field-name
# collision between this script and run-qa-install.sh's own
# `_write_result` - both called a field "present" while meaning two
# different things (`[ -f ]` exists-only here vs. `[ -s ]`
# nonempty-only there). Split into two separate, honestly-named
# fields below - never overloaded again.
#
# Usage: ./installer/scripts/extract-guest-evidence.sh \
#          <guest-evidence-log> <output-env> [<crash-output-dir>]

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <guest-evidence-log> <output-env> [<crash-output-dir>]" >&2
    exit 1
fi
GUEST_EVIDENCE_LOG="$1"
OUTPUT_ENV="$2"
CRASH_OUTPUT_DIR="${3:-$(dirname "${OUTPUT_ENV}")}"

mkdir -p "$(dirname "${OUTPUT_ENV}")"
mkdir -p "${CRASH_OUTPUT_DIR}"

# Section 18 bound - explicit, finite, never silently exceeded. Kept
# equal to the guest watcher's own QA_EVIDENCE_MAX_CRASH_FILES /
# QA_EVIDENCE_MAX_SNAP_FRAMES / QA_EVIDENCE_MAX_STORAGE_FRAMES
# (serein.installer.renderer) - a single shared conceptual cap per
# evidence kind, not independently-drifting numbers.
MAX_CRASH_FILES=5
MAX_SNAP_FRAMES=6
MAX_STORAGE_FRAMES=3

# Remove any stale artifact files from a previous run of this script
# against the same output directory - never leaves a prior run's
# now-stale numbered files lying around alongside a genuinely smaller
# count this run.
rm -f "${CRASH_OUTPUT_DIR}"/qa-install-block-probe-crash-*.txt 2>/dev/null || true
rm -f "${CRASH_OUTPUT_DIR}"/qa-install-snap-failure-frame-*.txt 2>/dev/null || true
rm -f "${CRASH_OUTPUT_DIR}"/qa-install-storage-probe-frame-*.txt 2>/dev/null || true

if [ ! -f "${GUEST_EVIDENCE_LOG}" ]; then
    {
        echo "# no guest evidence log present at ${GUEST_EVIDENCE_LOG}"
        echo "guest_evidence_log_exists=false"
        echo "guest_evidence_log_nonempty=false"
        echo "guest_evidence_crash_block_count=0"
        echo "guest_evidence_crash_block_nonempty_count=0"
        echo "guest_evidence_crash_block_truncated=false"
        echo "guest_evidence_snap_frame_count=0"
        echo "guest_evidence_snap_frame_truncated=false"
        echo "guest_evidence_snap_triggers="
        echo "guest_evidence_parse_error_count=0"
        echo "guest_evidence_watcher_started=false"
        echo "guest_evidence_watcher_start_ts="
        echo "guest_evidence_launcher_started=false"
        echo "guest_evidence_launcher_start_ts="
        echo "guest_evidence_launcher_completed=false"
        echo "guest_evidence_launcher_finish_ts="
        echo "storage_probe_frame_count=0"
        echo "storage_probe_frame_truncated=false"
        echo "storage_probe_triggers="
        echo "storage_probe_first_trigger="
        echo "storage_probe_first_trigger_ts="
        echo "storage_probe_device_serials_observed="
        echo "storage_probe_process_snapshot_present=false"
        echo "storage_probe_installer_log_present=false"
        echo "storage_probe_udisks_context_present=false"
        echo "storage_probe_frame_first_source="
        echo "storage_probe_frame_first_event_ts="
        echo "storage_probe_frame_first_capture_ts="
        echo "snapd_failure_precedes_portal_failure=unknown"
        echo "snapd_failure_precedes_desktop_security_center_failure=unknown"
        echo "snapd_failure_precedes_hold=unknown"
    } > "${OUTPUT_ENV}"
    exit 0
fi

if [ ! -s "${GUEST_EVIDENCE_LOG}" ]; then
    {
        echo "# guest evidence log exists but is empty at ${GUEST_EVIDENCE_LOG}"
        echo "guest_evidence_log_exists=true"
        echo "guest_evidence_log_nonempty=false"
        echo "guest_evidence_crash_block_count=0"
        echo "guest_evidence_crash_block_nonempty_count=0"
        echo "guest_evidence_crash_block_truncated=false"
        echo "guest_evidence_snap_frame_count=0"
        echo "guest_evidence_snap_frame_truncated=false"
        echo "guest_evidence_snap_triggers="
        echo "guest_evidence_parse_error_count=0"
        echo "guest_evidence_watcher_started=false"
        echo "guest_evidence_watcher_start_ts="
        echo "guest_evidence_launcher_started=false"
        echo "guest_evidence_launcher_start_ts="
        echo "guest_evidence_launcher_completed=false"
        echo "guest_evidence_launcher_finish_ts="
        echo "storage_probe_frame_count=0"
        echo "storage_probe_frame_truncated=false"
        echo "storage_probe_triggers="
        echo "storage_probe_first_trigger="
        echo "storage_probe_first_trigger_ts="
        echo "storage_probe_device_serials_observed="
        echo "storage_probe_process_snapshot_present=false"
        echo "storage_probe_installer_log_present=false"
        echo "storage_probe_udisks_context_present=false"
        echo "storage_probe_frame_first_source="
        echo "storage_probe_frame_first_event_ts="
        echo "storage_probe_frame_first_capture_ts="
        echo "snapd_failure_precedes_portal_failure=unknown"
        echo "snapd_failure_precedes_desktop_security_center_failure=unknown"
        echo "snapd_failure_precedes_hold=unknown"
    } > "${OUTPUT_ENV}"
    exit 0
fi

# A single awk pass over the raw evidence log, splitting it into
# discrete blocks of ANY kind. Each well-formed block is written to
# its own numbered file under CRASH_OUTPUT_DIR; a block missing its
# END marker (truncated mid-write, e.g. the host timeout killed QEMU
# while the guest was writing) is counted as a parse error and
# discarded rather than guessed at. Crash blocks are deduplicated by
# `filename=`; snap AND storage frames are deduplicated by `trigger=`
# (the guest watcher itself already exports each trigger at most once
# per run, but this is never trusted blindly here either) - the same
# real event re-exported is kept only once (the FIRST occurrence).
# Parser = evidence extraction only (Section 15) - this script never
# interprets root cause, it only surfaces what the guest itself wrote.
CRASH_DIR="${CRASH_OUTPUT_DIR}" awk -v max_crash="${MAX_CRASH_FILES}" -v max_snap="${MAX_SNAP_FRAMES}" \
    -v max_storage="${MAX_STORAGE_FRAMES}" '
    BEGIN {
        # CRASH_DIR is read via ENVIRON, never `-v` - a `-v` assignment
        # is escape-processed like an awk string literal, which would
        # silently mangle a real Windows-style path containing
        # backslashes (this project own established Windows/MSYS2
        # development environment, per S7.1R12/R13 established
        # performance-lesson discipline elsewhere in this directory).
        # An environment variable is taken literally, never escaped.
        crash_dir = ENVIRON["CRASH_DIR"]
        block_kind = ""
        parse_error_count = 0
        crash_seen_count = 0
        crash_nonempty_count = 0
        snap_seen_count = 0
        triggers_list = ""
        # S7.1R21: storage-probe frame state.
        storage_seen_count = 0
        storage_triggers_list = ""
        storage_first_trigger = ""
        storage_first_trigger_ts = ""
        # S7.1R22: HOW/WHEN the first frame actually fired - distinct
        # facts from storage_first_trigger/storage_first_trigger_ts
        # above (which is WHICH signal). Stay empty (never
        # "NOT_OBSERVED") for an old-format frame with no
        # trigger_source=/trigger_event_timestamp= lines, matching
        # every other unobserved-field convention already used
        # elsewhere in this script.
        storage_first_source = ""
        storage_first_event_ts = ""
        storage_first_capture_ts = ""
        storage_serial_protected_seen = 0
        storage_serial_target_seen = 0
        storage_process_snapshot_present = "false"
        storage_installer_log_present = "false"
        storage_udisks_context_present = "false"
        storage_awaiting_section = ""
        current_storage_trigger = ""
        current_storage_ts = ""
        # S7.1R16 Section 8/Objectives F-G: the boot marker and the
        # earliest observed value of each ordering timestamp across
        # EVERY parsed snap frame - "earliest" because a later frame
        # may re-observe an event that first became visible in an
        # earlier frame own bounded journal window.
        watcher_started = "false"
        watcher_start_ts = ""
        # S7.1R19 Section 8: the launcher marker defect - the launcher
        # (build_qa_evidence_launcher_script) already emitted
        # SEREIN_EVIDENCE_LAUNCHER_STARTED/_COMPLETED markers (with
        # launcher_start_ts=/launcher_finish_ts= on the line right
        # after each, the SAME two-line marker+field convention the
        # watcher boot marker already uses) since S7.1R17, but this
        # extractor never parsed them - guest_evidence_watcher_started
        # could read true while the launcher-level fields stayed
        # entirely absent from this script own output, even though
        # the launcher itself DID run. Fixed by generalizing the single
        # "await next line" state the watcher marker already used
        # (awaiting_field now names WHICH field is expected next,
        # rather than a single watcher-only boolean) to also recognize
        # both launcher markers.
        launcher_started = "false"
        launcher_start_ts = ""
        launcher_completed = "false"
        launcher_finish_ts = ""
        awaiting_field = ""
        min_hold_start_ts = ""
        min_portal_failure_ts = ""
        min_dsc_failure_ts = ""
        min_snapd_failure_ts = ""
    }
    /^SEREIN_EVIDENCE_WATCHER_STARTED$/ {
        watcher_started = "true"
        awaiting_field = "watcher_start_ts"
        next
    }
    /^SEREIN_EVIDENCE_LAUNCHER_STARTED$/ {
        launcher_started = "true"
        awaiting_field = "launcher_start_ts"
        next
    }
    /^SEREIN_EVIDENCE_LAUNCHER_COMPLETED$/ {
        launcher_completed = "true"
        awaiting_field = "launcher_finish_ts"
        next
    }
    {
        if (awaiting_field == "watcher_start_ts") {
            awaiting_field = ""
            if ($0 ~ /^watcher_start_monotonic_ts=/) {
                watcher_start_ts = substr($0, index($0, "=") + 1)
                next
            }
        } else if (awaiting_field == "launcher_start_ts") {
            awaiting_field = ""
            if ($0 ~ /^launcher_start_ts=/) {
                launcher_start_ts = substr($0, index($0, "=") + 1)
                next
            }
        } else if (awaiting_field == "launcher_finish_ts") {
            awaiting_field = ""
            if ($0 ~ /^launcher_finish_ts=/) {
                launcher_finish_ts = substr($0, index($0, "=") + 1)
                next
            }
        }
    }
    /^===BEGIN-CRASH-EVIDENCE===$/ {
        block_kind = "crash"
        buf = ""
        current_filename = ""
        current_crash_size = ""
        next
    }
    /^===END-CRASH-EVIDENCE===$/ {
        if (block_kind != "crash") { next }
        block_kind = ""
        if (current_filename == "") {
            parse_error_count++
            next
        }
        if (current_filename in seen_crash) { next }
        seen_crash[current_filename] = 1
        crash_seen_count++
        # S7.1R21 Section 14: a crash FILE existing is never the same
        # fact as its content being captured - a real S7.1R20 crash
        # file was 0 bytes (size=0). Tracked from the frame own
        # size= field, already present since S7.1R14.
        if (current_crash_size != "" && current_crash_size + 0 > 0) {
            crash_nonempty_count++
        }
        if (crash_seen_count > max_crash) { next }
        out = crash_dir "/qa-install-block-probe-crash-" crash_seen_count ".txt"
        printf "%s", buf > out
        close(out)
        next
    }
    /^=== SEREIN SNAP FAILURE FRAME ===$/ {
        block_kind = "snap"
        buf = ""
        current_trigger = ""
        next
    }
    /^=== END FRAME ===$/ {
        if (block_kind != "snap") { next }
        block_kind = ""
        if (current_trigger == "") {
            parse_error_count++
            next
        }
        if (current_trigger in seen_snap) { next }
        seen_snap[current_trigger] = 1
        snap_seen_count++
        triggers_list = (triggers_list == "" ? current_trigger : triggers_list "," current_trigger)
        if (snap_seen_count > max_snap) { next }
        out = crash_dir "/qa-install-snap-failure-frame-" snap_seen_count ".txt"
        printf "%s", buf > out
        close(out)
        next
    }
    /^=== SEREIN STORAGE PROBE FRAME ===$/ {
        block_kind = "storage"
        buf = ""
        current_storage_trigger = ""
        current_storage_ts = ""
        current_storage_source = ""
        current_storage_event_ts = ""
        current_storage_capture_ts = ""
        storage_awaiting_section = ""
        next
    }
    /^=== END STORAGE PROBE FRAME ===$/ {
        if (block_kind != "storage") { next }
        block_kind = ""
        if (current_storage_trigger == "") {
            parse_error_count++
            next
        }
        if (current_storage_trigger in seen_storage) { next }
        seen_storage[current_storage_trigger] = 1
        storage_seen_count++
        storage_triggers_list = (storage_triggers_list == "" ? current_storage_trigger \
            : storage_triggers_list "," current_storage_trigger)
        if (storage_first_trigger == "") {
            storage_first_trigger = current_storage_trigger
            storage_first_trigger_ts = current_storage_ts
            storage_first_source = current_storage_source
            storage_first_event_ts = current_storage_event_ts
            storage_first_capture_ts = current_storage_capture_ts
        }
        if (storage_seen_count > max_storage) { next }
        out = crash_dir "/qa-install-storage-probe-frame-" storage_seen_count ".txt"
        printf "%s", buf > out
        close(out)
        next
    }
    {
        if (block_kind == "crash") {
            if ($0 ~ /^filename=/) {
                current_filename = substr($0, 10)
            } else if ($0 ~ /^size=/) {
                current_crash_size = substr($0, index($0, "=") + 1)
            }
            buf = buf $0 "\n"
        } else if (block_kind == "storage") {
            if ($0 ~ /^trigger=/) {
                current_storage_trigger = substr($0, index($0, "=") + 1)
            } else if ($0 ~ /^timestamp=/) {
                current_storage_ts = substr($0, index($0, "=") + 1)
            } else if ($0 ~ /^trigger_source=/) {
                current_storage_source = substr($0, index($0, "=") + 1)
            } else if ($0 ~ /^trigger_event_timestamp=/) {
                current_storage_event_ts = substr($0, index($0, "=") + 1)
            } else if ($0 ~ /^frame_capture_timestamp=/) {
                current_storage_capture_ts = substr($0, index($0, "=") + 1)
            } else if ($0 ~ /^\[INSTALLER_LOG_/) {
                storage_awaiting_section = "installer_log"
            } else if ($0 ~ /^\[PROCESS_SNAPSHOT\]$/) {
                storage_awaiting_section = "process_snapshot"
            } else if ($0 ~ /^\[UDISKS_JOURNAL_CONTEXT\]$/ || $0 ~ /^\[UDISKS_PROCESS_SNAPSHOT\]$/) {
                storage_awaiting_section = "udisks_context"
            } else if (storage_awaiting_section != "") {
                if ($0 != "NOT_OBSERVED" && $0 != "") {
                    if (storage_awaiting_section == "installer_log") {
                        storage_installer_log_present = "true"
                    } else if (storage_awaiting_section == "process_snapshot") {
                        storage_process_snapshot_present = "true"
                    } else if (storage_awaiting_section == "udisks_context") {
                        storage_udisks_context_present = "true"
                    }
                }
                storage_awaiting_section = ""
            }
            if ($0 ~ /SEREIN-PROTECTED-DISK/) { storage_serial_protected_seen = 1 }
            if ($0 ~ /SEREIN-TARGET-DISK/) { storage_serial_target_seen = 1 }
            buf = buf $0 "\n"
        } else if (block_kind == "snap") {
            if ($0 ~ /^trigger=/) {
                current_trigger = substr($0, 9)
            } else if ($0 ~ /^hold_start_ts=/) {
                v = substr($0, index($0, "=") + 1)
                if (v != "NOT_OBSERVED" && (min_hold_start_ts == "" || v + 0 < min_hold_start_ts + 0)) {
                    min_hold_start_ts = v
                }
            } else if ($0 ~ /^portal_failure_ts=/) {
                v = substr($0, index($0, "=") + 1)
                if (v != "NOT_OBSERVED" && (min_portal_failure_ts == "" || v + 0 < min_portal_failure_ts + 0)) {
                    min_portal_failure_ts = v
                }
            } else if ($0 ~ /^dsc_failure_ts=/) {
                v = substr($0, index($0, "=") + 1)
                if (v != "NOT_OBSERVED" && (min_dsc_failure_ts == "" || v + 0 < min_dsc_failure_ts + 0)) {
                    min_dsc_failure_ts = v
                }
            } else if ($0 ~ /^snapd_failure_ts=/) {
                v = substr($0, index($0, "=") + 1)
                if (v != "NOT_OBSERVED" && (min_snapd_failure_ts == "" || v + 0 < min_snapd_failure_ts + 0)) {
                    min_snapd_failure_ts = v
                }
            }
            buf = buf $0 "\n"
        }
    }
    END {
        if (block_kind != "") {
            # a BEGIN with no matching END - truncated mid-write.
            parse_error_count++
        }
        printf "guest_evidence_log_exists=true\n"
        printf "guest_evidence_log_nonempty=true\n"
        printf "guest_evidence_crash_block_count=%d\n", crash_seen_count
        # S7.1R21 Section 14: file-exists is never conflated with
        # content-captured - a real S7.1R20 crash file was 0 bytes.
        printf "guest_evidence_crash_block_nonempty_count=%d\n", crash_nonempty_count
        printf "guest_evidence_crash_block_truncated=%s\n", (crash_seen_count > max_crash ? "true" : "false")
        printf "guest_evidence_snap_frame_count=%d\n", snap_seen_count
        printf "guest_evidence_snap_frame_truncated=%s\n", (snap_seen_count > max_snap ? "true" : "false")
        printf "guest_evidence_snap_triggers=%s\n", triggers_list
        printf "guest_evidence_parse_error_count=%d\n", parse_error_count

        # S7.1R21 storage probe internal-evidence instrumentation
        # summary - extraction only, never a root-cause interpretation
        # (Section 15 own explicit instruction).
        printf "storage_probe_frame_count=%d\n", storage_seen_count
        printf "storage_probe_frame_truncated=%s\n", \
            (storage_seen_count > max_storage ? "true" : "false")
        printf "storage_probe_triggers=%s\n", storage_triggers_list
        printf "storage_probe_first_trigger=%s\n", storage_first_trigger
        printf "storage_probe_first_trigger_ts=%s\n", storage_first_trigger_ts
        # S7.1R22: HOW/WHEN the first frame actually fired - see this
        # script header comment above for why these are distinct facts
        # from storage_probe_first_trigger/_ts above.
        printf "storage_probe_frame_first_source=%s\n", storage_first_source
        printf "storage_probe_frame_first_event_ts=%s\n", storage_first_event_ts
        printf "storage_probe_frame_first_capture_ts=%s\n", storage_first_capture_ts
        serials = ""
        if (storage_serial_protected_seen) { serials = "SEREIN-PROTECTED-DISK" }
        if (storage_serial_target_seen) {
            serials = (serials == "" ? "SEREIN-TARGET-DISK" : serials ",SEREIN-TARGET-DISK")
        }
        printf "storage_probe_device_serials_observed=%s\n", serials
        printf "storage_probe_process_snapshot_present=%s\n", storage_process_snapshot_present
        printf "storage_probe_installer_log_present=%s\n", storage_installer_log_present
        printf "storage_probe_udisks_context_present=%s\n", storage_udisks_context_present

        # S7.1R16 Section 8/Objectives F-G: honest ordering conclusions
        # only ever "true"/"false" when BOTH sides are real, observed
        # timestamps - "unknown" whenever either side is missing,
        # never guessed. A plain temporal observation, never a causal
        # claim (this script never emits a "CAUSED" field).
        printf "guest_evidence_watcher_started=%s\n", watcher_started
        printf "guest_evidence_watcher_start_ts=%s\n", watcher_start_ts
        # S7.1R19 Section 8: the launcher-marker-defect fix - the
        # launcher own two markers, now actually parsed (see this
        # script own header comment for the real prior defect).
        printf "guest_evidence_launcher_started=%s\n", launcher_started
        printf "guest_evidence_launcher_start_ts=%s\n", launcher_start_ts
        printf "guest_evidence_launcher_completed=%s\n", launcher_completed
        printf "guest_evidence_launcher_finish_ts=%s\n", launcher_finish_ts
        if (watcher_start_ts != "" && min_snapd_failure_ts != "") {
            printf "watcher_started_before_first_snapd_failure=%s\n", \
                (watcher_start_ts + 0 < min_snapd_failure_ts + 0 ? "true" : "false")
        } else {
            printf "watcher_started_before_first_snapd_failure=unknown\n"
        }
        if (min_snapd_failure_ts != "" && min_portal_failure_ts != "") {
            printf "snapd_failure_precedes_portal_failure=%s\n", \
                (min_snapd_failure_ts + 0 < min_portal_failure_ts + 0 ? "true" : "false")
        } else {
            printf "snapd_failure_precedes_portal_failure=unknown\n"
        }
        if (min_snapd_failure_ts != "" && min_dsc_failure_ts != "") {
            printf "snapd_failure_precedes_desktop_security_center_failure=%s\n", \
                (min_snapd_failure_ts + 0 < min_dsc_failure_ts + 0 ? "true" : "false")
        } else {
            printf "snapd_failure_precedes_desktop_security_center_failure=unknown\n"
        }
        if (min_snapd_failure_ts != "" && min_hold_start_ts != "") {
            printf "snapd_failure_precedes_hold=%s\n", \
                (min_snapd_failure_ts + 0 < min_hold_start_ts + 0 ? "true" : "false")
        } else {
            printf "snapd_failure_precedes_hold=unknown\n"
        }
    }
' "${GUEST_EVIDENCE_LOG}" > "${OUTPUT_ENV}"
