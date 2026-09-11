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
# Every extracted timestamp is the real console monotonic seconds
# value of the FIRST line in the serial log matching that milestone's
# pattern - a genuinely absent milestone is left EMPTY (NOT_OBSERVED),
# never fabricated or interpolated.
#
# S7.1R8 Objective B (real Run #8, RUN_ID=34355674598, proved
# R7_MILESTONE_PARSER_ACCURACY=PARTIAL_FAIL - four real defects fixed
# here):
#
#   Defect 1 (snapd_seeded_first_start omitted, not wrong): kernel
#   dmesg lines carry the standard bracketed `[  NNN.NNNNNN]` printk
#   timestamp, but systemd-journal-forwarded lines (everything
#   surfaced via S7.1R5's `systemd.journald.forward_to_console=1` -
#   i.e. every snapd/Subiquity/curtin unit-state message, which is
#   most of what this script actually needs to find) do not
#   necessarily carry that SAME bracket format. The timestamp
#   extractor below now accepts BOTH the bracketed kernel style and a
#   bare leading `NNN.NNNNNN` at line start - the field was being
#   OMITTED (empty), never populated with a WRONG value, which is the
#   exact signature of an extraction-format mismatch, not a
#   content-matching failure - the content pattern itself needed no
#   change.
#
#   Defect 2 (one raw event produced two milestone fields): the old
#   startup-timeout pattern's `Failed to start` alternative matched a
#   SEPARATE journal line systemd emits for the SAME single timeout
#   event (systemd routinely logs both a generic "Failed to start
#   X.service" line AND a specific "X.service: start operation timed
#   out" line for one real failure) - narrowed to match ONLY the one
#   canonical, specific message per real event, so
#   ONE_RAW_TIMEOUT_EVENT => ONE_MILESTONE_EVENT holds.
#
#   Defect 3 (AppArmor profile-load line misclassified as a real hook
#   failure): the old pattern
#   (`desktop-security-center.*hook`) matched ANY line mentioning both
#   substrings, including a perfectly normal, SUCCESSFUL AppArmor
#   profile-load announcement whose profile NAME happens to contain
#   both words (e.g. `profile="snap.desktop-security-center.hook.configure"`).
#   Real hook failure detection is now a real, two-stage, semantic
#   match (see `_desktop_security_center_hook_failure_timestamp`):
#   POSITIVE evidence requires an explicit failure/error term
#   co-occurring with the hook reference; apparmor profile-load
#   announcement lines are explicitly EXCLUDED regardless of what
#   other words they contain.
#
#   Defect 4 (generic snap activity misclassified as mass removal):
#   the old pattern's broad `Remove.*[Ss]nap|removing snap`
#   alternatives could match a single, routine snap operation, never
#   actually evidence of Run #7's real mass removal/remount sequence.
#   Narrowed to the one specific, real snapd internal task-kind name
#   Run #7's own evidence actually showed (`RemoveSnapServices`) -
#   per this script's own stated forensic-tooling principle,
#   FALSE_NEGATIVE_WITH_UNKNOWN (an empty field) is always preferable
#   to FALSE_POSITIVE_WITH_WRONG_FACT.
#
# S7.1R9 Objective B (real Run #9, RUN_ID=34371427617): R8's parser
# was STILL partially defective - R9_MILESTONE_PARSER_ACCURACY=PARTIAL_FAIL.
#
#   Root cause (PROVEN): the old `_first_timestamp_for`/
#   `_nth_timestamp_for`/hook-failure helpers all used
#   `grep -m1 <pattern> | extract-timestamp` (or an equivalent
#   content-then-head pipeline) - i.e. FIRST_CONTENT_MATCH, THEN try
#   to extract a timestamp. Real Run #9 evidence proved the guest
#   serial log can contain an UNTIMESTAMPED line (console/splash
#   duplication of the same underlying event, carrying no leading
#   `[NNN.NNNNNN]`/`NNN.NNNNNN` prefix at all) that matches a
#   milestone's content pattern BEFORE any real, timestamped
#   occurrence of that same milestone - `grep -m1` locks onto that
#   first, timestamp-less line and never looks further, so the field
#   was left empty even though a real, later, timestamped line
#   existed (`snapd_seeded_first_start=` empty, despite the real
#   ``[379.857234] Starting snapd.seeded.service`` line existing
#   further down the log).
#
#   Fix: every extraction helper below now searches ALL matching
#   lines (never `-m1`/`head`-truncated before a timestamp check) and
#   returns the FIRST (or Nth, for indexed milestones) one that
#   actually carries a parseable timestamp - a content match with no
#   timestamp is skipped entirely, never counted as an "occurrence"
#   for Nth-indexing purposes either (this is also the correct fix
#   for "do not count splash/journal duplication as a separate real
#   event" - an untimestamped duplicate line can never consume a
#   real event's ordinal slot). Never fabricates or interpolates a
#   timestamp for a line that has none.
#
# S7.1R11 (real Run #11, RUN_ID=34489050155): Run #11 reproduced a
# catastrophic snap lifecycle closely matching Run #7's real, earlier
# evidence (a ~3944s unstable-seed window: three distinct
# snapd.seeded attempts, a desktop-security-center configure-hook
# sanity-timeout failure, a real mass RemoveSnapServices/remount
# sequence, a `/snap/snapd/current` missing window, before a final
# stable seed) - CATASTROPHIC_SNAP_LIFECYCLE_RECURRENCE=PROVEN across
# historical runs (#6 ~557.5s, #7 ~3044s pathological, #8 ~450s,
# #9 ~399s, #10 ~467.5s, #11 ~3943s pathological). This is host-side
# forensics ONLY - this script does not, and will never, attempt to
# prevent, mask, or shortcut this real upstream snap/live-session
# behavior; RAW_SERIAL_LOG remains the one authoritative source for
# any causal investigation.
#
#   Defect (real, PROVEN via Run #11): `snapd_seeded_success`'s old
#   pattern (`Finished snapd\.seeded|Reached target.*Cloud-init`)
#   could match a GENERIC, UNRELATED `Reached target Cloud-init...`
#   systemd boot-target line as if it were a real snapd.seeded success
#   - Run #11 derived output wrongly reported
#   `snapd_seeded_success≈984.407227` while the real, final, stable
#   `Finished snapd.seeded.service` event was at ≈4397.845s. Fixed:
#   narrowed to ONLY `Finished snapd\.seeded` - an explicit successful
#   completion event for snapd.seeded.service itself, never inferred
#   from any later, unrelated boot-target reached-event.
#
#   New: a genuine MULTI-ATTEMPT seed-lifecycle model
#   (`_extract_seed_attempts`, Section 17) - a single, chronological,
#   real Change-adjacent state-machine over every real
#   "Starting snapd.seeded.service" / "Finished snapd.seeded.service"
#   / snapd.seeded-failure line, emitting `seed_attempt_<n>_start`/
#   `_finish`/`_result` for however many real attempts actually
#   occurred (never hardcoded, never collapsed to a single first/
#   success pair) plus `seed_attempt_count`, `final_stable_seed_success`
#   (the LAST attempt's own finish timestamp, but ONLY if that last
#   attempt's own result is "success" - i.e. no later
#   snapd.seeded failure/restart exists after it, per this script's
#   own Section 19 definition), and `unstable_seed_window_duration`
#   (first attempt's start -> final_stable_seed_success). New:
#   `snapd_hold_finish` (captured as a plain forensic data point, never
#   classified as causally responsible for anything without direct
#   evidence - see docs/installer/known-limitations.md's own R11
#   causality discussion), `snap_removal_last`/`snap_removal_event_count`
#   (Section 14 - honest RAW LINE-MATCH counts, never claimed to be a
#   verified count of distinct affected snap names, which this script
#   has no reliable way to determine from timestamps/patterns alone).
#
# RAW_SERIAL_LOG=AUTHORITATIVE. DERIVED_MILESTONES (this file) are a
# NON_AUTHORITATIVE forensic convenience summary only - if a derived
# field ever disagrees with the raw serial log, the raw serial log
# wins. This file is never used as a Layer-B success/failure gate.
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

# _extract_timestamp - reads ONE line on stdin and prints its leading
# monotonic-seconds timestamp, robust to BOTH real observed serial-
# console formats (S7.1R8 Defect 1): kernel/dmesg bracketed style
# (`[  NNN.NNNNNN] message`) and the bare, unbracketed style
# systemd-journal-forwarded lines may use (`NNN.NNNNNN message`).
# Empty if the line has neither - never fabricated.
_extract_timestamp() {
    grep -Eo '^[[:space:]]*\[?[[:space:]]*[0-9]+\.[0-9]+\]?' \
        | grep -Eo '[0-9]+\.[0-9]+' \
        | head -n1 || true
}

# _first_valid_timestamp_from_lines - reads candidate (already
# content-filtered) lines on stdin and returns the timestamp of the
# FIRST one that actually HAS a valid, parseable timestamp - a
# candidate line that matched on CONTENT but carries no timestamp
# (S7.1R9's proven root cause: a splash/console echo duplicate of a
# real, timestamped event elsewhere in the log) is skipped entirely,
# never treated as if it settled the search. Always returns 0 (via the
# explicit trailing `return 0`) regardless of whether a timestamp was
# ultimately found, so callers piping `grep ... | _first_valid_timestamp_from_lines`
# are inherently `pipefail`-safe without needing a separate `|| true`.
_first_valid_timestamp_from_lines() {
    local line ts
    while IFS= read -r line; do
        ts="$(printf '%s\n' "${line}" | _extract_timestamp)"
        if [ -n "${ts}" ]; then
            printf '%s\n' "${ts}"
            return 0
        fi
    done
    return 0
}

# _normalize_event_content - reads ONE line on stdin and prints a
# normalized form of its MESSAGE content: the leading timestamp token
# (kernel-bracket or bare style) and a common syslog/journal
# "process[pid]:" metadata prefix are stripped, then the remainder is
# case-folded and internal whitespace collapsed. Two DIFFERENT
# serialized renderings of the exact same real event (S7.1R10's proven
# real defect - a genuine timeout event appearing twice in the raw log
# with identical content but under a different console/journal
# rendering) normalize to the SAME string; two genuinely different
# events never do, even if one happens to share a timestamp with the
# other (used only for within-one-milestone-pattern dedup - see
# _nth_valid_timestamp_from_lines - never to match content across
# different milestone patterns, each of which already scopes its own
# search to one specific event class).
_normalize_event_content() {
    local line
    IFS= read -r line
    # Deliberately narrow: strips ONLY the leading timestamp token
    # (kernel-bracket or bare style - the one, real, PROVEN source of
    # "harmless rendering difference" between two rederings of the
    # same real event, e.g. `[  597.856803] msg` vs `597.856803 msg`),
    # then case-folds and collapses whitespace. Earlier drafts of this
    # function also tried to strip an assumed leading
    # "process[pid]:"-style syslog/journal prefix - removed after
    # direct testing proved it unsafe: a real message's own content
    # can itself look exactly like "word:" (e.g. the genuine message
    # text "snapd.service: start operation timed out." starts with
    # "snapd.service:"), so that heuristic could strip REAL message
    # content instead of actual metadata noise, silently treating two
    # DIFFERENT real messages as identical - exactly the
    # false-positive-with-wrong-fact failure mode this script's own
    # header says is never acceptable. A conservative rule that
    # sometimes fails to merge two prefix-different renderings of one
    # real event (an honest FALSE_NEGATIVE_WITH_UNKNOWN, i.e. an extra
    # counted occurrence when unsure) is always preferable to one that
    # can silently merge two real, distinct events.
    printf '%s\n' "${line}" \
        | sed -E 's/^[[:space:]]*\[?[[:space:]]*[0-9]+\.[0-9]+\]?[[:space:]]*//' \
        | tr '[:upper:]' '[:lower:]' \
        | tr -s '[:space:]' ' '
}

# _nth_valid_timestamp_from_lines <n> - the same skip-untimestamped-
# candidates discipline as _first_valid_timestamp_from_lines, but
# returns the Nth (1-indexed) candidate that actually has a valid
# timestamp AND represents a genuinely NEW semantic occurrence - an
# untimestamped candidate line is never counted toward n (S7.1R9), and
# S7.1R10 Objective C: a candidate whose (timestamp, normalized
# content) pair is IDENTICAL to the immediately preceding counted
# occurrence is treated as a duplicate SERIALIZED RENDERING of that
# SAME real event, never a distinct new occurrence - real Run #10
# evidence proved a single real timeout event, logged twice at the
# identical timestamp 597.856803s, was wrongly counted as both the
# first AND second occurrence. Requiring BOTH the timestamp AND the
# normalized content to match (never timestamp alone) is the
# conservative guard against accidentally collapsing two genuinely
# distinct events that merely happen to share a timestamp - their
# differing content keeps them counted separately.
_nth_valid_timestamp_from_lines() {
    local n="$1" line ts count=0 prev_ts="" prev_line=""
    while IFS= read -r line; do
        ts="$(printf '%s\n' "${line}" | _extract_timestamp)"
        if [ -n "${ts}" ]; then
            # The (comparatively expensive) semantic-identity check
            # only ever runs when two candidates' TIMESTAMPS actually
            # collide - a rare case in practice - never on every
            # candidate line, so the common (non-colliding) path stays
            # as cheap as it was before Objective C.
            if [ "${ts}" = "${prev_ts}" ]; then
                if [ "$(printf '%s\n' "${line}" | _normalize_event_content)" \
                     = "$(printf '%s\n' "${prev_line}" | _normalize_event_content)" ]; then
                    continue
                fi
            fi
            prev_ts="${ts}"
            prev_line="${line}"
            count=$((count + 1))
            if [ "${count}" -eq "${n}" ]; then
                printf '%s\n' "${ts}"
                return 0
            fi
        fi
    done
    return 0
}

# _first_timestamp_for <pattern> - the timestamp of the FIRST line
# matching <pattern> (grep -Ei) that actually HAS a valid timestamp,
# or empty if no such match - never fabricated. Never `grep -m1`
# (S7.1R9's proven root cause of a real defect - see this script's own
# header) - searches ALL matching lines, so a timestamp-less first
# content match can never mask a real, later, timestamped occurrence.
_first_timestamp_for() {
    local pattern="$1"
    # `|| true` is REQUIRED even though _first_valid_timestamp_from_lines
    # itself always returns 0: under `pipefail`, the pipeline's status
    # is the LAST NON-ZERO stage's status if ANY stage failed, not
    # merely the rightmost stage's status - a genuinely-absent
    # milestone's `grep` correctly exits 1 when it finds nothing,
    # which would otherwise abort the whole script under `set -e`
    # even though the reader function itself handled the empty input
    # correctly.
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null \
        | _first_valid_timestamp_from_lines || true
}

# _last_valid_timestamp_from_lines - the same skip-untimestamped-
# candidates discipline as _first_valid_timestamp_from_lines, but
# keeps scanning to the end and returns the LAST candidate's
# timestamp - used for S7.1R11 Section 14's
# REMOVE_SNAP_SERVICES_LAST_TIMESTAMP (a real mass-removal sequence
# can span many real lines; this reports the last one actually
# observed, never fabricated/interpolated). Always returns 0.
_last_valid_timestamp_from_lines() {
    local line ts last=""
    while IFS= read -r line; do
        ts="$(printf '%s\n' "${line}" | _extract_timestamp)"
        if [ -n "${ts}" ]; then
            last="${ts}"
        fi
    done
    printf '%s\n' "${last}"
    return 0
}

# _last_timestamp_for <pattern> - the timestamp of the LAST line
# matching <pattern> that actually HAS a valid timestamp, or empty if
# no such match - never fabricated.
_last_timestamp_for() {
    local pattern="$1"
    # See _first_timestamp_for's comment on why `|| true` is required.
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null \
        | _last_valid_timestamp_from_lines || true
}

# _nth_timestamp_for <pattern> <n> - the Nth (1-indexed) matching
# line's timestamp, counting only lines that actually have one - used
# for "second occurrence" milestones (snap_second_client_timeout) so a
# genuine second event is never conflated with the first, and a
# timestamp-less duplicate line is never miscounted as an occurrence.
_nth_timestamp_for() {
    local pattern="$1" n="$2"
    # See _first_timestamp_for's comment on why `|| true` is required.
    grep -Ei -- "${pattern}" "${SERIAL_LOG}" 2>/dev/null \
        | _nth_valid_timestamp_from_lines "${n}" || true
}

# _desktop_security_center_hook_failure_timestamp - S7.1R8 Defect 3:
# a real, two-stage, semantic match rather than one loose regex.
# POSITIVE: a line mentioning both "desktop-security-center" and
# "hook" AND an UNAMBIGUOUS failure/error term ("exit code" is
# deliberately excluded from this list - "exit code 0" describes
# SUCCESS, so a bare "exit code" substring can never safely imply
# failure on its own). NEGATIVE: excludes AppArmor profile-LOAD
# announcement lines, which legitimately mention both words as part of
# a normal, SUCCESSFUL profile name (e.g.
# profile="snap.desktop-security-center.hook.configure") and are never
# evidence of a real failure on their own. Uses the same S7.1R9
# skip-untimestamped-candidates discipline as every other helper here.
_desktop_security_center_hook_failure_timestamp() {
    # See _first_timestamp_for's comment on why `|| true` is required.
    grep -Ei -- 'desktop-security-center.*hook' "${SERIAL_LOG}" 2>/dev/null \
        | grep -Ei -- 'fail|error|denied|non-zero' \
        | grep -Eiv -- 'apparmor_parser|profile_load|operation="profile_load"' \
        | _first_valid_timestamp_from_lines || true
}

# _extract_seed_attempts - S7.1R11 Objective D / Section 17: a SINGLE,
# chronological pass over every real snapd.seeded-related line,
# building a genuine multi-attempt seed-lifecycle record - never
# collapses a real multi-attempt sequence (real Run #11's proven
# ~3943s / 3-attempt pathological sequence) down to a single first/
# success pair.
#
# Classifies each candidate line as start ("Starting snapd.seeded...",
# the real, confirmed format - see this script's own header), finish
# ("Finished snapd.seeded...", a genuine successful completion), or
# fail (any other snapd.seeded line containing "fail"), using a plain
# substring search (never a regex) so no line's real content can be
# misread. A consecutive duplicate (same timestamp, same
# classification) is treated as a duplicate SERIALIZED RENDERING of
# the same real event (S7.1R10's own established principle), never a
# new attempt boundary.
#
# Emits one start/finish/result triple per real attempt actually
# observed - N is never hardcoded. An attempt that opens but never
# reaches an observed finish/fail before the next start (or before the
# log ends) is honestly recorded with result=unknown and an empty
# finish - never fabricated or assumed successful.
_extract_seed_attempts() {
    grep -Ei -- 'snapd\.seeded' "${SERIAL_LOG}" 2>/dev/null | awk '
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

            lower = tolower(line)
            is_start = (index(lower, "starting snapd.seeded") > 0)
            is_finish = (index(lower, "finished snapd.seeded") > 0)
            is_fail = (!is_finish && index(lower, "fail") > 0)
            if (!is_start && !is_finish && !is_fail) next

            kind = is_start ? "start" : (is_finish ? "finish" : "fail")
            if (ts == last_ts && kind == last_kind) next
            last_ts = ts
            last_kind = kind

            if (is_start) {
                if (have_open) {
                    n++
                    starts[n] = open_start
                    finishes[n] = ""
                    results[n] = "unknown"
                }
                open_start = ts
                have_open = 1
            } else if (have_open) {
                n++
                starts[n] = open_start
                finishes[n] = ts
                results[n] = is_finish ? "success" : "fail"
                have_open = 0
            }
        }
        END {
            if (have_open) {
                n++
                starts[n] = open_start
                finishes[n] = ""
                results[n] = "unknown"
            }
            for (i = 1; i <= n; i++) {
                printf "seed_attempt_%d_start=%s\n", i, starts[i]
                printf "seed_attempt_%d_finish=%s\n", i, finishes[i]
                printf "seed_attempt_%d_result=%s\n", i, results[i]
            }
            printf "seed_attempt_count=%d\n", n
        }
    ' || true
}

# _remove_snap_services_event_count - S7.1R11 Section 14: an honest
# RAW LINE-MATCH count of real, timestamped RemoveSnapServices
# occurrences - deliberately NEVER claimed to be a verified count of
# DISTINCT affected snap names (this script has no reliable way to
# associate a RemoveSnapServices line with a specific snap name from
# timestamps/patterns alone; overclaiming that would be exactly the
# FALSE_POSITIVE_WITH_WRONG_FACT failure mode this script's own header
# forbids).
_remove_snap_services_event_count() {
    grep -Ei -- 'RemoveSnapServices' "${SERIAL_LOG}" 2>/dev/null | awk '
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
    ' || true
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
    snap_removal_last
    snapd_current_missing
    snap_second_client_timeout
    ntp_10m_timeout
    snapd_seeded_success
    snapd_hold_finish
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
    'snapd\.service:.*start operation timed out'
    'snapd\.service:.*start operation timed out'
    'desktop-security-center.*hook'
    'sanity timeout'
    'RemoveSnapServices'
    'RemoveSnapServices'
    '/snap/snapd/current.*no such file or directory'
    'cannot communicate with server|timeout exceeded while waiting for response'
    'no NTP sync after'
    'Finished snapd\.seeded'
    'Finished snapd\.hold'
    'extract_autoinstall|load_cloud_config'
    'load_autoinstall_config'
    'apply_autoinstall_config'
    'Install/install'
    'curtin --showtrace|curtin: Installing|python3.*curtin'
    'apt.config|apt-config'
)

{
    echo "# S7.1R7/R8 - bounded, host-side, NON_AUTHORITATIVE forensic"
    echo "# summary of the real guest serial log (RAW_SERIAL_LOG is"
    echo "# always the authoritative source). Each value is the real"
    echo "# monotonic-seconds timestamp of the FIRST matching line -"
    echo "# empty means NOT_OBSERVED in this run's serial log, never"
    echo "# fabricated."
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
            # S7.1R8 Defect 3: a real, two-stage, semantic match - see
            # _desktop_security_center_hook_failure_timestamp's own
            # docstring. Never the generic single-pattern path, which
            # a real AppArmor profile-load announcement can trivially
            # satisfy without indicating any real failure.
            desktop_security_center_hook_failure)
                ts="$(_desktop_security_center_hook_failure_timestamp)"
                ;;
            # S7.1R11 Section 14: the LAST observed occurrence, not the
            # first - a real mass-removal sequence's own end.
            snap_removal_last)
                ts="$(_last_timestamp_for "${pattern}")"
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

# S7.1R11 Section 17: the real multi-attempt seed lifecycle, appended
# once (a single ordered pass - see _extract_seed_attempts's own
# docstring), never per-milestone.
_extract_seed_attempts >> "${OUTPUT}"

# S7.1R11 Section 14: an honest raw line-match count only.
echo "snap_removal_event_count=$(_remove_snap_services_event_count)" >> "${OUTPUT}"

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

# S7.1R11 Section 19: "final stable seed success" is defined as the
# LAST recorded attempt's own finish timestamp, but ONLY if that last
# attempt's own result is "success" - by construction (the attempts
# are strictly chronological), this means no later snapd.seeded
# failure/restart exists after it. If the log ends mid-attempt, or the
# last attempt's own result is "fail"/"unknown", this is honestly left
# empty - never inferred from an earlier, non-final success (real
# Run #7/#11 both proved an EARLIER "Finished snapd.seeded.service"
# can be followed by a LATER real failure/restart, so the first
# success is never automatically the stable one).
{
    seed_attempt_count="$(grep -m1 '^seed_attempt_count=' "${OUTPUT}" 2>/dev/null | cut -d= -f2)"
    final_stable_seed_success=""
    if [ -n "${seed_attempt_count}" ] && [ "${seed_attempt_count}" -gt 0 ] 2>/dev/null; then
        last_result="$(grep -m1 "^seed_attempt_${seed_attempt_count}_result=" "${OUTPUT}" 2>/dev/null | cut -d= -f2)"
        if [ "${last_result}" = "success" ]; then
            final_stable_seed_success="$(grep -m1 "^seed_attempt_${seed_attempt_count}_finish=" "${OUTPUT}" 2>/dev/null | cut -d= -f2)"
        fi
    fi
    echo "final_stable_seed_success=${final_stable_seed_success}"
} >> "${OUTPUT}"

{
    echo "snapd_seed_duration=$(_duration snapd_seeded_first_start snapd_seeded_success)"
    echo "seed_finish_to_subiquity_load=$(_duration snapd_seeded_success subiquity_autoinstall_load)"
    echo "subiquity_load_to_install=$(_duration subiquity_autoinstall_load subiquity_install_enter)"
    echo "install_to_curtin=$(_duration subiquity_install_enter curtin_start)"
    echo "curtin_runtime_before_qemu_exit=$(_duration curtin_start qemu_timeout)"
    # S7.1R11 Section 19: first observed attempt's start -> the final
    # STABLE success (never the first success) - real Run #11 proof
    # this must never be collapsed to the old two-field
    # snapd_seed_duration, which real Run #7/#11 evidence already
    # proved can badly understate the true unstable window if an
    # early, non-final "Finished snapd.seeded.service" happens to
    # exist before a later real failure/restart.
    echo "unstable_seed_window_duration=$(_duration seed_attempt_1_start final_stable_seed_success)"
} >> "${OUTPUT}"
