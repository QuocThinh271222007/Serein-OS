#!/usr/bin/env bash
# S7.1R13 Objectives A-F: bounded, host-side, read-only extraction of
# real Subiquity/probert/os-prober storage-probe forensic evidence
# from the real QEMU guest serial log.
#
# Real Run #13 (RUN_ID=34706519567) entered Subiquity/autoinstall but
# never reached real Curtin storage partitioning - by >6200s,
# filesystem probes were still being attempted (Filesystem/_probe/
# probe_once cycling between restricted=False failures/cancellations
# and restricted=True successes, then another unrestricted probe)
# before the 6600s host timeout killed QEMU.
# SUBIQUITY_STORAGE_PROBE_FAILURE=PROVEN,
# FILESYSTEM_APPLY_AUTOINSTALL_CONFIG_COMPLETION=NOT_OBSERVED,
# CURTIN_PARTITIONING_STARTED=NOT_OBSERVED.
#
# Public, real upstream evidence (canonical/subiquity,
# bugs.launchpad.net/subiquity - consulted during this corrective,
# never fabricated) confirms:
#   - the real log format is "... probe_once: FAIL: cancelled" and
#     "ERROR block-discover:NNN block probing failed restricted=False"
#     (LP #1868817, LP #2024011);
#   - probe_once carries a documented internal timeout on its own full
#     probe task (LP #1868817 cites a real 15.0s
#     `self._probe_once_task.task` wait), and Subiquity's own
#     controller architecture is DESIGNED to fall back from an
#     unrestricted (full) probe to a restricted probe on failure, then
#     re-attempt an unrestricted probe later - i.e. the
#     unrestricted->restricted->unrestricted cycle Run #13 observed is
#     a documented, intentional Subiquity resilience pattern, not
#     inherently a hang by itself;
#   - Subiquity's own `match` autoinstall directive (serial/model/
#     vendor/path/id_path/devpath/ssd/size/install-media) and
#     probert's own public interface expose NO documented mechanism to
#     exclude a specific, visible block device from being probed -
#     probert's whole design is to probe every visible device;
#     `match` only affects which ALREADY-PROBED disk gets SELECTED
#     for installation afterward. SAFE_PROBE_MITIGATION_FOUND=false
#     follows directly from this - see
#     docs/installer/known-limitations.md's own S7.1R13 section for
#     the full citation trail.
#
# Architectural note (same constraint as S7.1R12's
# extract-snap-change-forensics.sh - read before assuming this script
# performs live in-guest crash-report collection): this project's
# ONLY host<->guest channel is the QEMU `-serial file:...` console log
# (installer/scripts/run-qa-install.sh's own QEMU_ARGS - no shared
# folder, no 9p mount, no virtio-fs share). The live installer's own
# ephemeral filesystem (where /var/crash/*.crash would actually live)
# is discarded entirely once QEMU exits - there is structurally no way
# to "copy files out of the guest after QEMU exits" without a
# materially larger architecture change (a new shared-storage
# mechanism) than one corrective round justifies. This script
# therefore extracts real crash-report/probe-failure EVIDENCE FROM
# THE TEXT of the same already-captured serial console log (crash-
# reporter/apport/Subiquity's own log lines are journald-forwarded to
# that console thanks to S7.1R5's `systemd.journald.forward_to_console=1`
# fix) rather than performing any live guest-side file collection - a
# genuinely absent crash-report MENTION in the console text is honest
# NOT_OBSERVED evidence, never fabricated, and never claimed to be
# equivalent to a full copy of the real crash-report file's contents.
#
# RAW_SERIAL_LOG=AUTHORITATIVE. This script's output is a
# NON_AUTHORITATIVE forensic convenience summary only, never a
# Layer-B gate - a missing serial log or zero matches both produce a
# valid, honest, empty-field output file.
#
# Every field name is a plain OBSERVATION, never an encoded causal
# conclusion (Section 10) - e.g. `protected_disk_probe_observed=true`
# is a fact this script may assert; `protected_disk_caused_failure=`
# is a judgment this script never makes.
#
# Curtin's own real "start: cmd-install/stage-X"/"finish: ...
# stage-X" event-logging convention (stage-partitioning, stage-extract,
# stage-curthooks) is the ONLY evidence this script accepts as proof
# of real destructive partitioning having started - an "apt-config"
# mention alone is explicitly NEVER treated as partitioning evidence
# (Objective G point 7 - a real, named prior mistake this script must
# not repeat).
#
# Usage: ./installer/scripts/extract-storage-probe-forensics.sh <serial-log> <output-path>
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

# Section 10 bound - explicit, finite, documented. Truncation is
# always recorded, never silent.
MAX_SUMMARY_CHARS=200

_extract_timestamp() {
    grep -Eo '^[[:space:]]*\[?[[:space:]]*[0-9]+\.[0-9]+\]?' \
        | grep -Eo '[0-9]+\.[0-9]+' \
        | head -n1 || true
}

# Shared awk fragment (never a per-line subshell fork - S7.1R12's own
# proven, measured performance lesson: a while-read loop invoking a
# subshell helper per matching line took ~45s against just 29
# matches on this project's Windows/MSYS2 development environment;
# every counting/extraction helper below does its timestamp-parsing
# work in a SINGLE awk process instead) - extracts either the kernel-
# bracketed `[ NNN.NNNNNN]` or bare `NNN.NNNNNN` leading timestamp
# into awk's own `ts` variable; empty if neither form is present.
# shellcheck disable=SC2016
_AWK_AWK_TS_EXTRACT='
    ts = ""
    if (match($0, /\[[ \t]*[0-9]+\.[0-9]+\]/)) {
        ts = substr($0, RSTART, RLENGTH)
        gsub(/[^0-9.]/, "", ts)
    } else if (match($0, /^[ \t]*[0-9]+\.[0-9]+/)) {
        ts = substr($0, RSTART, RLENGTH)
        gsub(/^[ \t]+/, "", ts)
    }
'

# _count_timestamped_matches <pattern> - a single grep+awk pass
# counting only lines that BOTH match <pattern> AND carry a valid,
# parseable timestamp - never a bare `grep -c`, which would also
# count an untimestamped duplicate rendering (S7.1R9-R12's own
# established discipline).
_count_timestamped_matches() {
    local pattern="$1"
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null | awk "
        { ${_AWK_AWK_TS_EXTRACT}
          if (ts != \"\") count++ }
        END { printf \"%d\n\", count }
    " || true
}

# _last_valid_timestamp_for <pattern> - the timestamp of the LAST
# matching line that actually has one - never fabricated. Single awk
# pass (never a per-line subshell).
_last_valid_timestamp_for() {
    local pattern="$1"
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null | awk "
        { ${_AWK_AWK_TS_EXTRACT}
          if (ts != \"\") last = ts }
        END { printf \"%s\n\", last }
    " || true
}

# _count_lines_matching_all <pattern1> <pattern2> [...] - a chain of
# grep stages, each filtering the PREVIOUS stage's output for another
# required substring/pattern, then a single awk pass counts only
# lines that also carry a valid timestamp. Genuinely ORDER-
# INDEPENDENT: unlike a single combined regex (e.g. `A.*B`), which
# requires A to appear BEFORE B in the line, each grep stage only
# checks "this substring exists somewhere in the line" - a real,
# proven-necessary distinction (real Run #13-class evidence includes
# lines like "block probing failed restricted=False", where the
# outcome word "failed" appears BEFORE the "restricted=False" token,
# the opposite order a naive `restricted=False.*failed` regex would
# require). Each grep stage is one subprocess regardless of how many
# lines flow through it - never one subprocess per matching line.
_count_lines_matching_all() {
    local acc
    acc="$(cat "${SERIAL_LOG}" 2>/dev/null)" || true
    local pat
    for pat in "$@"; do
        acc="$(printf '%s' "${acc}" | grep -Ei -- "${pat}" 2>/dev/null)" || true
        [ -n "${acc}" ] || { echo 0; return 0; }
    done
    printf '%s\n' "${acc}" | awk "
        { ${_AWK_AWK_TS_EXTRACT}
          if (ts != \"\") count++ }
        END { printf \"%d\n\", count }
    "
}

# _first_valid_timestamp_matching_all <pattern1> <pattern2> [...] -
# same order-independent AND-chain, returning the FIRST valid
# timestamp among the surviving lines via a single awk pass - never
# `grep -m1` (S7.1R9's proven root cause of a real, different defect -
# see extract-bootstrap-milestones.sh's own header) since a
# timestamp-less match must never mask a later, real, timestamped one.
_first_valid_timestamp_matching_all() {
    local acc
    acc="$(cat "${SERIAL_LOG}" 2>/dev/null)" || true
    local pat
    for pat in "$@"; do
        acc="$(printf '%s' "${acc}" | grep -Ei -- "${pat}" 2>/dev/null)" || true
        [ -n "${acc}" ] || return 0
    done
    printf '%s\n' "${acc}" | awk "
        { if (found) next
          ${_AWK_AWK_TS_EXTRACT}
          if (ts != \"\") { print ts; found = 1 } }
    " || true
}

# _storage_probe_state_machine <probe_pat> <unrestricted_tok>
#   <restricted_tok> <success_pat> <failure_pat>
#
# Single awk pass modeling real probe-attempt open/close semantics
# (S7.1R14 Objective G - see the call site's own comment for the full
# rationale). Emits `SPSM_<NAME>=<int>` assignment lines on stdout,
# meant to be consumed via `eval "$(...)"` at the call site - every
# value here is a plain integer this script itself computed, never
# untrusted input echoed back.
_storage_probe_state_machine() {
    local probe_pat="$1" unrestricted_tok="$2" restricted_tok="$3"
    local success_pat="$4" failure_pat="$5"
    grep -Ei -- "${probe_pat}" "${SERIAL_LOG}" 2>/dev/null | awk \
        -v unrestricted="${unrestricted_tok}" \
        -v restricted="${restricted_tok}" \
        -v success_pat="${success_pat}" \
        -v failure_pat="${failure_pat}" '
        BEGIN {
            n_open = 0
            start_u = 0; success_u = 0; failure_u = 0
            start_r = 0; success_r = 0; failure_r = 0
            unassociated_failure = 0
            last_key = ""
        }
        {
            line = $0
            ts = ""
            if (match(line, /\[[ \t]*[0-9]+\.[0-9]+\]/)) {
                ts = substr(line, RSTART, RLENGTH)
                gsub(/[^0-9.]/, "", ts)
            } else if (match(line, /^[ \t]*[0-9]+\.[0-9]+/)) {
                ts = substr(line, RSTART, RLENGTH)
                gsub(/^[ \t]+/, "", ts)
            }
            if (ts == "") next

            # Duplicate SERIALIZED rendering of the exact same real
            # event (identical timestamp AND identical normalized
            # content) - deduplicated. Two genuinely distinct events
            # that merely share a timestamp have different normalized
            # content and so a different key - never conflated.
            norm = line
            gsub(/^[ \t]*\[?[ \t]*[0-9]+\.[0-9]+\]?[ \t]*/, "", norm)
            key = ts SUBSEP norm
            if (key == last_key) next
            last_key = key

            is_u = (line ~ unrestricted)
            is_r = (line ~ restricted)
            is_fail = (line ~ failure_pat)
            is_success = (line ~ success_pat)

            if (is_fail || is_success) {
                if (is_u || is_r) {
                    # Self-contained result - this line carries its own
                    # restricted= token, so its mode is real evidence,
                    # never guessed. Counted directly regardless of any
                    # open attempt; if a matching-mode attempt happens
                    # to be open, consume (close) it too, so it is
                    # never left dangling as still-open.
                    mode = is_u ? "u" : "r"
                    if (mode == "u") { if (is_fail) failure_u++; else success_u++ }
                    else { if (is_fail) failure_r++; else success_r++ }
                    for (k = n_open; k >= 1; k--) {
                        if (open_mode[k] == mode) {
                            for (j = k; j < n_open; j++) { open_mode[j] = open_mode[j + 1] }
                            n_open--
                            break
                        }
                    }
                } else {
                    # Ambiguous result (e.g. real "probe_once: FAIL:
                    # cancelled" - no restricted= token of its own) -
                    # associate with the MOST RECENTLY opened
                    # still-open attempt, whichever mode that is
                    # (Section 10: never guessed when none is open).
                    if (n_open >= 1) {
                        mode = open_mode[n_open]
                        n_open--
                        if (mode == "u") { if (is_fail) failure_u++; else success_u++ }
                        else { if (is_fail) failure_r++; else success_r++ }
                    } else if (is_fail) {
                        unassociated_failure++
                    }
                }
            } else if (is_u || is_r) {
                mode = is_u ? "u" : "r"
                if (mode == "u") start_u++; else start_r++
                n_open++
                open_mode[n_open] = mode
            }
        }
        END {
            printf "SPSM_START_U=%d\n", start_u
            printf "SPSM_SUCCESS_U=%d\n", success_u
            printf "SPSM_FAILURE_U=%d\n", failure_u
            printf "SPSM_START_R=%d\n", start_r
            printf "SPSM_SUCCESS_R=%d\n", success_r
            printf "SPSM_FAILURE_R=%d\n", failure_r
            printf "SPSM_UNASSOCIATED_FAILURE=%d\n", unassociated_failure
        }
    ' || true
}

{
    echo "# S7.1R13 Objectives A-F - bounded, host-side,"
    echo "# NON_AUTHORITATIVE Subiquity/probert/os-prober storage-probe"
    echo "# forensic summary, extracted from the real guest serial log"
    echo "# (RAW_SERIAL_LOG is always the authoritative source)."
    echo "# Empty/absent/zero means NOT_OBSERVED in this run's serial"
    echo "# log, never fabricated. Every field here is a plain"
    echo "# observation, never an encoded causal conclusion - see this"
    echo "# script's own header."

    # -- Objective B: unrestricted vs. restricted probe_once cycle.
    # Real upstream log formats accepted: the paraphrased
    # "probe_once restricted=False/True" form and the real, cited
    # "block probing failed restricted=False" form (LP #2024011).
    # Every multi-token check below uses the order-independent
    # AND-chain helpers - a real "block probing failed
    # restricted=False" line has "failed" BEFORE "restricted=False",
    # the opposite order a single combined `restricted=False.*failed`
    # regex would require. --
    probe_once_or_block='([Pp]robe_once|block.probing)'
    unrestricted_tok='restricted=False'
    restricted_tok='restricted=True'
    outcome_success='(succeeded|success)'
    outcome_failure='(fail|FAIL|cancel|Cancel)'

    # S7.1R14 Objective G (Run #14 real evidence: this exact
    # single-line-AND approach reported
    # filesystem_probe_unrestricted_start_count=6,
    # filesystem_probe_unrestricted_failure_count=0 despite raw
    # evidence containing "probe_once: FAIL: cancelled" - a real,
    # cited-upstream "bare" failure line that never carries its own
    # "restricted=" token on the same line, so a naive single-line AND
    # match against unrestricted_tok+outcome_failure can never match
    # it). Modeled instead as a semantic attempt state machine
    # (_storage_probe_state_machine, below): a "start" line opens an
    # attempt in its own restricted=True/False mode; a "result" line
    # that ITSELF carries an explicit restricted= token is
    # self-contained (counted directly, regardless of any open
    # attempt); a "result" line with NO restricted= token is
    # ambiguous - it closes the MOST RECENTLY opened still-open
    # attempt (whichever mode that is), never guessed when no attempt
    # is open (Section 10 - "do not fabricate"), and instead recorded
    # under filesystem_probe_unassociated_failure_count. Duplicate
    # SERIALIZED renderings of the exact same real event (identical
    # timestamp AND identical normalized content) are deduplicated;
    # distinct events that merely happen to share a timestamp are
    # never conflated (S7.1R12's own established discipline, applied
    # here to storage-probe events for the first time). --
    eval "$(_storage_probe_state_machine "${probe_once_or_block}" "${unrestricted_tok}" "${restricted_tok}" "${outcome_success}" "${outcome_failure}")"

    echo "filesystem_probe_unrestricted_start_count=${SPSM_START_U}"
    echo "filesystem_probe_unrestricted_success_count=${SPSM_SUCCESS_U}"
    echo "filesystem_probe_unrestricted_failure_count=${SPSM_FAILURE_U}"

    echo "filesystem_probe_restricted_start_count=${SPSM_START_R}"
    echo "filesystem_probe_restricted_success_count=${SPSM_SUCCESS_R}"
    echo "filesystem_probe_restricted_failure_count=${SPSM_FAILURE_R}"

    # Section 10: a failure event with no explicit restricted= token of
    # its own AND no matching open attempt to associate with - real,
    # honest NOT_OBSERVED-mode evidence, never guessed into either
    # bucket above.
    echo "filesystem_probe_unassociated_failure_count=${SPSM_UNASSOCIATED_FAILURE}"

    # -- Objective F: Filesystem-controller-specific apply_autoinstall
    # start/finish - distinct from the generic top-level
    # apply_autoinstall_config milestone already tracked by
    # extract-bootstrap-milestones.sh. "finish" requires an EXPLICIT
    # completion marker on a Filesystem-scoped line - never inferred
    # from a later, unrelated event (Objective G point 6). --
    echo "filesystem_apply_autoinstall_start=$(_first_valid_timestamp_matching_all 'Filesystem' 'apply_autoinstall_config')"
    echo "filesystem_apply_autoinstall_finish=$(_first_valid_timestamp_matching_all 'Filesystem' 'apply_autoinstall_config' '(finish|complete|Complete|done|Done|applied|Applied)')"

    # -- Objective G point 7 / Section 2's own explicit warning: ONLY
    # curtin's real "start:"/"finish:" stage-event convention counts
    # as partitioning evidence - an "apt-config" mention alone can
    # NEVER satisfy this. --
    echo "partitioning_stage_start=$(_first_valid_timestamp_matching_all 'start:' 'stage-partitioning')"
    echo "partitioning_stage_finish=$(_first_valid_timestamp_matching_all 'finish:' 'stage-partitioning')"

    echo "os_prober_invocation_count=$(_count_timestamped_matches 'os-prober')"

    # -- Section 4 / Objective B.3-4: device visibility during
    # probing - purely observational, never a causal claim. Device
    # patterns match the BARE disk path OR any partition suffix
    # (/dev/vda, /dev/vda1, /dev/vda2, ...) - real Section 4 evidence
    # explicitly lists partition-suffixed paths
    # (/dev/vda1 /dev/vda2 /dev/vdb1 /dev/vdb2), so a bare `\b`
    # word-boundary directly after "vda"/"vdb" would never match them
    # (no boundary exists between a letter and a following digit). --
    probe_context='([Pp]robe|probert|os-prober|block.discover|blkid)'
    protected_dev='/dev/vda[0-9]*\b'
    target_dev='/dev/vdb[0-9]*\b'

    vda_hits="$(_count_lines_matching_all "${probe_context}" "${protected_dev}")"
    vdb_hits="$(_count_lines_matching_all "${probe_context}" "${target_dev}")"
    echo "protected_disk_probe_observed=$([ "${vda_hits}" -gt 0 ] && echo true || echo false)"
    echo "target_disk_probe_observed=$([ "${vdb_hits}" -gt 0 ] && echo true || echo false)"

    last_probe_ts="$(_last_valid_timestamp_for "${probe_once_or_block}|${probe_context}")"
    echo "last_storage_probe_timestamp=${last_probe_ts}"

    # -- Objective A: crash-report MENTIONS in the console text only -
    # never a live file copy (see this script's own architectural
    # note above). --
    crash_count="$(_count_timestamped_matches '/var/crash/[^[:space:]]*\.crash')"
    echo "block_probe_crash_report_present=$([ "${crash_count}" -gt 0 ] && echo true || echo false)"
    echo "block_probe_crash_report_count=${crash_count}"

    block_probe_fail_count="$(
        {
            _count_lines_matching_all "block.probing" "failed"
            _count_timestamped_matches 'block_probe_fail'
        } | awk '{s+=$1} END {print s+0}'
    )"
    echo "block_probe_failure_observed=$([ "${block_probe_fail_count}" -gt 0 ] && echo true || echo false)"
    echo "block_probe_failure_count=${block_probe_fail_count}"

    # A bounded, honest best-effort "which device appears most often
    # in probe-context lines" - empty if zero or tied (never an
    # arbitrary tie-break). Reuses vda_hits/vdb_hits already computed
    # above for protected_disk_probe_observed/target_disk_probe_observed.
    probe_primary_device=""
    if [ "${vda_hits}" -gt "${vdb_hits}" ]; then
        probe_primary_device="/dev/vda"
    elif [ "${vdb_hits}" -gt "${vda_hits}" ]; then
        probe_primary_device="/dev/vdb"
    fi
    echo "probe_primary_device=${probe_primary_device}"

    # A bounded, truncation-honest one-line summary of the FIRST real
    # probe-failure line - real message content only, never
    # fabricated/interpolated. Order-independent AND-chain, same as
    # every counting helper above.
    summary_raw="$(
        {
            acc="$(cat "${SERIAL_LOG}" 2>/dev/null)"
            acc="$(printf '%s' "${acc}" | grep -Ei -- "${probe_once_or_block}" 2>/dev/null)" || true
            acc="$(printf '%s' "${acc}" | grep -Ei -- "${unrestricted_tok}" 2>/dev/null)" || true
            acc="$(printf '%s' "${acc}" | grep -Ei -- "${outcome_failure}" 2>/dev/null)" || true
            printf '%s\n' "${acc}" | head -n1
        }
    )" || true
    if [ -z "${summary_raw}" ]; then
        summary_raw="$(grep -Ei -m1 -- 'block_probe_fail' "${SERIAL_LOG}" 2>/dev/null || true)"
    fi
    truncated="false"
    summary_text="${summary_raw}"
    if [ "${#summary_raw}" -gt "${MAX_SUMMARY_CHARS}" ]; then
        summary_text="${summary_raw:0:${MAX_SUMMARY_CHARS}}"
        truncated="true"
    fi
    echo "probe_primary_failure_summary=${summary_text}"
    echo "storage_probe_forensics_truncated=${truncated}"
} > "${OUTPUT}"
