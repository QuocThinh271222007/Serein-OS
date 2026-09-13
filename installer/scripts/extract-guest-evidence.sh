#!/usr/bin/env bash
# S7.1R14 Objective A / S7.1R15 Objective B: bounded, host-side,
# read-only extraction of the QA-only guest evidence channel into a
# compact summary + per-item artifact files.
#
# `run-qa-install.sh`'s QEMU_ARGS wire a dedicated virtio-serial port
# (org.serein.qa.evidence) backed by a `-chardev file,...` sink
# (qa-install-guest-evidence.log) - a real, structurally one-way QEMU
# backend the guest may only WRITE into (see run-qa-install.sh's own
# QEMU_ARGS comment for the full safety rationale). The guest-side
# watcher (serein.installer.renderer._qa_evidence_watcher_script,
# embedded via an early-commands autoinstall directive) appends two
# kinds of bounded blocks to that sink:
#
#   ===BEGIN-CRASH-EVIDENCE===/===END-CRASH-EVIDENCE===
#       whenever it observes a new /var/crash/*block_probe_fail*.crash
#       file (S7.1R14 - the block-probe pathology).
#   === SEREIN SNAP FAILURE FRAME ===/=== END FRAME ===
#       whenever it observes one of the recurring snap/bootstrap
#       pathology signals (S7.1R15 - desktop-security-center hook
#       failure, sanity timeout, RemoveSnapServices, a missing
#       /snap/snapd/current, or a snapd.seeded failure).
#
# Run #16 (or any future run) may reproduce EITHER pathology family,
# BOTH, or NEITHER - this script handles all four cases and always
# produces a valid, honest output (S7.1R15 Section 22).
#
# This script turns that raw text into:
#
#   <output-env>                                          - summary
#   <crash-output-dir>/qa-install-block-probe-crash-N.txt - bounded
#       per-crash artifacts (block-probe pathology)
#   <crash-output-dir>/qa-install-snap-failure-frame-N.txt - bounded
#       per-frame artifacts (snap/bootstrap pathology)
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
# QA_EVIDENCE_MAX_SNAP_FRAMES (serein.installer.renderer) - a single
# shared conceptual cap per evidence kind, not independently-drifting
# numbers.
MAX_CRASH_FILES=5
MAX_SNAP_FRAMES=5

# Remove any stale artifact files from a previous run of this script
# against the same output directory - never leaves a prior run's
# now-stale numbered files lying around alongside a genuinely smaller
# count this run.
rm -f "${CRASH_OUTPUT_DIR}"/qa-install-block-probe-crash-*.txt 2>/dev/null || true
rm -f "${CRASH_OUTPUT_DIR}"/qa-install-snap-failure-frame-*.txt 2>/dev/null || true

if [ ! -f "${GUEST_EVIDENCE_LOG}" ]; then
    {
        echo "# no guest evidence log present at ${GUEST_EVIDENCE_LOG}"
        echo "guest_evidence_log_exists=false"
        echo "guest_evidence_log_nonempty=false"
        echo "guest_evidence_crash_block_count=0"
        echo "guest_evidence_crash_block_truncated=false"
        echo "guest_evidence_snap_frame_count=0"
        echo "guest_evidence_snap_frame_truncated=false"
        echo "guest_evidence_snap_triggers="
        echo "guest_evidence_parse_error_count=0"
    } > "${OUTPUT_ENV}"
    exit 0
fi

if [ ! -s "${GUEST_EVIDENCE_LOG}" ]; then
    {
        echo "# guest evidence log exists but is empty at ${GUEST_EVIDENCE_LOG}"
        echo "guest_evidence_log_exists=true"
        echo "guest_evidence_log_nonempty=false"
        echo "guest_evidence_crash_block_count=0"
        echo "guest_evidence_crash_block_truncated=false"
        echo "guest_evidence_snap_frame_count=0"
        echo "guest_evidence_snap_frame_truncated=false"
        echo "guest_evidence_snap_triggers="
        echo "guest_evidence_parse_error_count=0"
    } > "${OUTPUT_ENV}"
    exit 0
fi

# A single awk pass over the raw evidence log, splitting it into
# discrete blocks of EITHER kind. Each well-formed block is written to
# its own numbered file under CRASH_OUTPUT_DIR; a block missing its
# END marker (truncated mid-write, e.g. the host timeout killed QEMU
# while the guest was writing) is counted as a parse error and
# discarded rather than guessed at. Crash blocks are deduplicated by
# `filename=`; snap frames are deduplicated by `trigger=` (the guest
# watcher itself already exports each trigger at most once per run,
# but this is never trusted blindly here either) - the same real event
# re-exported is kept only once (the FIRST occurrence).
CRASH_DIR="${CRASH_OUTPUT_DIR}" awk -v max_crash="${MAX_CRASH_FILES}" -v max_snap="${MAX_SNAP_FRAMES}" '
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
        snap_seen_count = 0
        triggers_list = ""
    }
    /^===BEGIN-CRASH-EVIDENCE===$/ {
        block_kind = "crash"
        buf = ""
        current_filename = ""
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
    {
        if (block_kind == "crash") {
            if ($0 ~ /^filename=/) {
                current_filename = substr($0, 10)
            }
            buf = buf $0 "\n"
        } else if (block_kind == "snap") {
            if ($0 ~ /^trigger=/) {
                current_trigger = substr($0, 9)
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
        printf "guest_evidence_crash_block_truncated=%s\n", (crash_seen_count > max_crash ? "true" : "false")
        printf "guest_evidence_snap_frame_count=%d\n", snap_seen_count
        printf "guest_evidence_snap_frame_truncated=%s\n", (snap_seen_count > max_snap ? "true" : "false")
        printf "guest_evidence_snap_triggers=%s\n", triggers_list
        printf "guest_evidence_parse_error_count=%d\n", parse_error_count
    }
' "${GUEST_EVIDENCE_LOG}" > "${OUTPUT_ENV}"
