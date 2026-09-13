#!/usr/bin/env bash
# S7.1R14 Objective A: bounded, host-side, read-only extraction of the
# QA-only guest crash-evidence channel into a compact summary +
# per-crash artifact files.
#
# `run-qa-install.sh`'s QEMU_ARGS wire a dedicated virtio-serial port
# (org.serein.qa.evidence) backed by a `-chardev file,...` sink
# (qa-install-guest-evidence.log) - a real, structurally one-way QEMU
# backend the guest may only WRITE into (see run-qa-install.sh's own
# QEMU_ARGS comment for the full safety rationale). The guest-side
# watcher (serein.installer.renderer._qa_evidence_watcher_script,
# embedded via an early-commands autoinstall directive) appends bounded
# ===BEGIN-CRASH-EVIDENCE===/===END-CRASH-EVIDENCE=== blocks to that
# sink whenever it observes a new /var/crash/*block_probe_fail*.crash
# file. This script turns that raw text into:
#
#   <output-env>                                  - summary fields
#   <crash-output-dir>/qa-install-block-probe-crash-N.txt  - per-crash
#                                                    bounded artifacts
#
# Never fails the job - a missing/empty guest-evidence log, or
# malformed/unparseable block content, all produce a valid, honest
# output rather than a non-zero exit (matches every other extractor
# script in this directory - RAW_SERIAL_LOG/RAW_GUEST_EVIDENCE_LOG
# remain the authoritative source; this is a non-authoritative,
# read-only forensic convenience only).
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
# equal to the guest watcher's own QA_EVIDENCE_MAX_CRASH_FILES
# (serein.installer.renderer) - a single shared conceptual cap, not two
# independently-drifting numbers.
MAX_CRASH_FILES=5

# Remove any stale crash artifact files from a previous run of this
# script against the same output directory - never leaves a prior run's
# now-stale qa-install-block-probe-crash-N.txt lying around alongside a
# genuinely smaller count this run.
rm -f "${CRASH_OUTPUT_DIR}"/qa-install-block-probe-crash-*.txt 2>/dev/null || true

if [ ! -f "${GUEST_EVIDENCE_LOG}" ]; then
    {
        echo "# no guest evidence log present at ${GUEST_EVIDENCE_LOG}"
        echo "guest_evidence_log_present=false"
        echo "guest_evidence_crash_block_count=0"
        echo "guest_evidence_crash_block_truncated=false"
        echo "guest_evidence_parse_error_count=0"
    } > "${OUTPUT_ENV}"
    exit 0
fi

if [ ! -s "${GUEST_EVIDENCE_LOG}" ]; then
    {
        echo "# guest evidence log present but empty at ${GUEST_EVIDENCE_LOG}"
        echo "guest_evidence_log_present=true"
        echo "guest_evidence_crash_block_count=0"
        echo "guest_evidence_crash_block_truncated=false"
        echo "guest_evidence_parse_error_count=0"
    } > "${OUTPUT_ENV}"
    exit 0
fi

# A single awk pass over the raw evidence log, splitting it into
# discrete BEGIN/END blocks. Each well-formed block is written to its
# own numbered file under CRASH_OUTPUT_DIR; a block missing its END
# marker (truncated mid-write, e.g. the host timeout killed QEMU while
# the guest was writing) is counted as a parse error and discarded
# rather than guessed at. Deduplicated by `filename=` - the same real
# crash file re-exported by the guest (should not happen given the
# guest's own dedup, but never trusted blindly here either) is written
# only once, keeping the FIRST occurrence.
CRASH_DIR="${CRASH_OUTPUT_DIR}" awk -v max_files="${MAX_CRASH_FILES}" '
    BEGIN {
        # CRASH_DIR is read via ENVIRON, never `-v` - a `-v` assignment
        # is escape-processed like an awk string literal, which would
        # silently mangle a real Windows-style path containing
        # backslashes (this project own established Windows/MSYS2
        # development environment, per S7.1R12/R13 established
        # performance-lesson discipline elsewhere in this directory).
        # An environment variable is taken literally, never escaped.
        crash_dir = ENVIRON["CRASH_DIR"]
        in_block = 0
        parse_error_count = 0
        seen_count = 0
    }
    /^===BEGIN-CRASH-EVIDENCE===$/ {
        in_block = 1
        buf = ""
        current_filename = ""
        next
    }
    /^===END-CRASH-EVIDENCE===$/ {
        if (!in_block) { next }
        in_block = 0
        if (current_filename == "") {
            parse_error_count++
            next
        }
        if (current_filename in seen) { next }
        seen[current_filename] = 1
        seen_count++
        if (seen_count > max_files) { next }
        out = crash_dir "/qa-install-block-probe-crash-" seen_count ".txt"
        printf "%s", buf > out
        close(out)
        next
    }
    {
        if (in_block) {
            if ($0 ~ /^filename=/) {
                current_filename = substr($0, 10)
            }
            buf = buf $0 "\n"
        }
    }
    END {
        if (in_block) {
            # a BEGIN with no matching END - truncated mid-write.
            parse_error_count++
        }
        printf "guest_evidence_log_present=true\n"
        printf "guest_evidence_crash_block_count=%d\n", seen_count
        printf "guest_evidence_crash_block_truncated=%s\n", (seen_count > max_files ? "true" : "false")
        printf "guest_evidence_parse_error_count=%d\n", parse_error_count
    }
' "${GUEST_EVIDENCE_LOG}" > "${OUTPUT_ENV}"
