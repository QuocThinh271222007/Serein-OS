"""Subiquity/curtin autoinstall config rendering (S7.1 Sections 5-7,
25-26, 35).

Pipeline this module is the last, narrow step of (Section 25):

    disk evidence -> Serein plan -> Serein safety validation ->
    installer config renderer -> Subiquity/curtin

Never the reverse - this module refuses to render anything from a
plan whose ``validation.valid`` is not ``True`` (never "raw YAML
straight to Subiquity" - Section 25). It is also QA-only by
construction: every rendering entrypoint requires an explicit
``qa_mode=True`` keyword, and raises if it is not given, so a future
caller cannot accidentally wire this into a production code path
without a deliberate, visible change (Section 6-7).

**Output format note**: the rendered text is produced via
``json.dumps`` rather than a YAML library - this project intentionally
ships zero runtime dependencies (see ``pyproject.toml``), and JSON is a
syntactic subset of YAML, so the output is genuine, valid
``autoinstall.yaml`` content Subiquity parses like any other YAML
document.

**Schema fidelity caveat** (documented again in
``docs/installer/known-limitations.md``): the curtin storage
action-list shape below follows curtin's own documented "storage
config version 2" action schema, but has not been validated against a
real curtin/Subiquity invocation in this development environment (no
``xorriso``/``qemu``/Subiquity installed here) - see
``docs/distribution/upstream-installer-research.md`` for the same
caveat pattern S7.0 already applied to its own UEFI-evidence
heuristic.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from serein.installer.models import TARGET_ESP_FILESYSTEM, TARGET_ESP_SIZE_BYTES, InstallPlan
from serein.installer.models import TARGET_ROOT_FILESYSTEM as _TARGET_ROOT_FILESYSTEM
from serein.installer.payload import InstallStateMarker, QaCredential

# re-exported for callers that only need the filesystem name, matching
# the naming already used elsewhere in this module
TARGET_ROOT_FILESYSTEM = _TARGET_ROOT_FILESYSTEM

# S7.1R14 Objective A: guest-side bounded crash-evidence watcher
# constants (Section 11 - explicit, finite bounds, never unbounded).
# QA_EVIDENCE_WATCHER_MAX_ITERATIONS * QA_EVIDENCE_WATCHER_SLEEP_SECONDS
# is deliberately set to the SAME 6600s ceiling as
# run-qa-install.sh's own QEMU_TIMEOUT_SECONDS - the watcher is
# guaranteed to self-terminate at or before the host would kill QEMU
# anyway, never relying on the guest ever shutting down gracefully
# (Run #14 was itself killed by the host timeout).
QA_EVIDENCE_MAX_CRASH_FILES = 5
QA_EVIDENCE_MAX_BYTES_PER_CRASH = 4096
QA_EVIDENCE_WATCHER_MAX_ITERATIONS = 660
QA_EVIDENCE_WATCHER_SLEEP_SECONDS = 10
QA_EVIDENCE_PORT_PATH = "/dev/virtio-ports/org.serein.qa.evidence"

# S7.1R15 Objective B: guest-side bounded snap/bootstrap-pathology
# watcher constants (Section 7-8). Runs #7/#11/#12/#15 all reproduced
# the same recurring, nondeterministic snap-lifecycle pathology
# (desktop-security-center configure-hook failure -> sanity timeout ->
# RemoveSnapServices -> a missing /snap/snapd/current -> full snap
# reconstruction) while Runs #13/#14 had a normal single-attempt seed -
# this watcher captures a bounded diagnostic frame the FIRST time each
# of the five known signals is observed, never more than once per
# signal per run (Section 6 - observation only, never a trigger for
# any corrective action, never a control channel).
QA_EVIDENCE_MAX_SNAP_FRAMES = 6
QA_EVIDENCE_MAX_BYTES_PER_SNAP_FRAME = 16384
# S7.1R16 Objective B: dynamic, bounded capture of the actual failed
# snap Change task graph (never hardcoded to Change ID 1 - Run #16's
# own Change 1 was real, but a future run may fail on any other ID).
QA_EVIDENCE_MAX_FAILED_CHANGE_IDS = 5
# S7.1R16: frames now carry substantially more per-item detail (the
# failed-Change task graph, snapd.service properties/journal context,
# last-progress-before-timeout, and a process snapshot) - the shared
# total ceiling is raised again accordingly, still small, explicit,
# and never unbounded.
QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES = 262144
# S7.1R21 Objective (storage probe internal-evidence instrumentation):
# a third bounded frame kind, capturing the FIRST occurrence of each
# of three known Filesystem/_probe/probe_once storage-probe failure
# signals (a real S7.1R20 forensic finding - see
# build_qa_evidence_watcher_script's own docstring). Deliberately
# small (3, one per known trigger, each deduplicated) - never one per
# poll iteration. The existing QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES
# ceiling is left UNCHANGED: 5*4096 + 6*16384 + 3*32768 = 217088,
# still comfortably under the existing 262144 ceiling, so raising it
# is not necessary (Section 13's own "only if necessary" instruction).
QA_EVIDENCE_MAX_STORAGE_FRAMES = 3
QA_EVIDENCE_MAX_BYTES_PER_STORAGE_FRAME = 32768
# S7.1R22 (storage probe TRIGGER reliability corrective - forensic
# instrumentation only, never a storage/installer behavioral change):
# R21-TCG-REPRO-1 proved a real R20 storage-probe failure (probe_once
# cancelled + block_probe_fail) occurred in-guest while the watcher
# and evidence channel were both demonstrably alive, yet
# storage_probe_frame_count stayed 0. The shared 200-line
# `recent_journal` snapshot used for storage-TRIGGER DETECTION (never
# the frame's own separate, wider CONTENT fetch, which was already
# fine) is the prime suspect: under a busy boot, unrelated journal
# volume can scroll the real trigger line out of the last-200-line
# window between one 10s poll and the next, before the watcher ever
# sees it. Detection now uses a per-poll `journalctl --after-cursor`
# batch when the guest's journalctl supports it (verified at watcher
# startup, never assumed), bounded by these two ceilings so a busy
# journal still cannot make this detection step unbounded; the
# bounded-window fallback (guest journalctl lacking cursor support)
# reuses the SAME ceilings.
QA_EVIDENCE_MAX_STORAGE_DETECTION_LINES = 4000
QA_EVIDENCE_MAX_STORAGE_DETECTION_BYTES = 262144

# S7.1R16 Objective A / S7.1R17 corrective: the watcher script is
# embedded as a real file at the QA-install ISO's own root (never the
# squashfs - see prepare_qa_install_iso's own docstring). Named here,
# not in isoprep.py, since both the launcher script (below) and
# isoprep's own file-writing wiring need this SAME filename and must
# never drift apart into two independently-typed string literals.
#
# S7.1R19 corrective: the LAUNCHER is no longer written as a separate
# ISO-root file - it is base64-embedded directly into an early-commands
# autoinstall directive instead (see
# _qa_evidence_launcher_early_command's own docstring for why) - so
# there is no longer a QA_EVIDENCE_LAUNCHER_ISO_FILENAME constant.
QA_EVIDENCE_WATCHER_ISO_FILENAME = "serein-qa-early-watcher.sh"
# S7.1R17: the name of the independent, systemd-managed transient unit
# the launcher hands the long-running watcher off to - see
# build_qa_evidence_launcher_script's own docstring for the real Run
# #17 defect this corrects.
QA_EVIDENCE_WATCHER_UNIT_NAME = "serein-qa-evidence-watcher"


class RendererError(ValueError):
    """Raised when asked to render from an unvalidated/invalid plan, or
    outside explicit QA mode - fail closed rather than ever emit a
    config the safety gate has not actually approved."""


def _require_valid_plan(plan: InstallPlan) -> None:
    if not plan.validation.valid:
        raise RendererError(
            "refusing to render an installer config from a plan that is not "
            f"validation.valid=True (reasons: {list(plan.validation.reasons)})"
        )


def render_autoinstall_storage_config(plan: InstallPlan) -> dict[str, Any]:
    """Curtin storage-config-v2 action list for ``plan`` (Section 26 -
    explicit/action-based, never ``largest``/``smallest``/first-match).
    The disk-match stanza is built ONLY from real evidence the selected
    target's own identity carries (serial, then wwn, then the observed
    path as the final anchor) - never an implicit selection policy.
    """
    _require_valid_plan(plan)

    identity = plan.target
    match: dict[str, str] = {}
    if identity.serial:
        match["serial"] = identity.serial
    if identity.wwn:
        match["wwn"] = identity.wwn
    match["path"] = plan.target_device_path

    actions: list[dict[str, Any]] = [
        {
            "type": "disk",
            "id": "disk-target",
            "match": match,
            "wipe": "superblock-recursive",
            "ptable": "gpt",
            "grub_device": True,
            "preserve": False,
        },
        {
            "type": "partition",
            "id": "partition-esp",
            "device": "disk-target",
            "size": TARGET_ESP_SIZE_BYTES,
            "flag": "boot",
            "grub_device": True,
        },
        {
            "type": "format",
            "id": "format-esp",
            "volume": "partition-esp",
            "fstype": TARGET_ESP_FILESYSTEM,
            "label": "SEREIN_ESP",
        },
        {
            "type": "partition",
            "id": "partition-root",
            "device": "disk-target",
            "size": -1,
        },
        {
            "type": "format",
            "id": "format-root",
            "volume": "partition-root",
            "fstype": TARGET_ROOT_FILESYSTEM,
            "label": "SEREIN_ROOT",
        },
        {"type": "mount", "id": "mount-root", "device": "format-root", "path": "/"},
        {"type": "mount", "id": "mount-esp", "device": "format-esp", "path": "/boot/efi"},
    ]
    return {"config": actions}


def _install_state_late_command(marker: InstallStateMarker) -> str:
    """One shell one-liner that writes ``marker`` into the freshly
    installed target's ``/etc/serein/install-state.json`` - base64
    round-tripped so the JSON content's own quoting never has to be
    escaped into the outer shell/JSON string (Section 27)."""
    encoded = base64.b64encode(
        (json.dumps(marker.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).decode("ascii")
    return (
        "curtin in-target -- sh -c "
        f"'mkdir -p /etc/serein && echo {encoded} | base64 -d > /etc/serein/install-state.json'"
    )


def build_qa_evidence_watcher_script() -> str:
    """The guest-side bounded evidence producer for THREE recurring
    pathology families this project has observed (S7.1R14 Objective A
    + S7.1R15 Objective B + S7.1R16 Objectives A-G + S7.1R21 storage
    probe internal-evidence instrumentation). A POSIX ``/bin/sh``
    script (no bashisms - the live ISO's default shell is dash) that:

    1. emits a single ``SEREIN_EVIDENCE_WATCHER_STARTED`` marker with a
       monotonic timestamp the moment it starts (S7.1R16 Objective A/8) -
       the only way to actually PROVE this watcher started earlier than
       the pathology, rather than merely asserting it exists;
    2. watches for new ``/var/crash/*block_probe_fail*.crash`` files
       (the Run #13/#14 block-probe pathology) and exports bounded
       metadata + truncated content;
    3. watches the guest's own systemd journal for six known signals of
       the recurring Run #7/#11/#12/#15/#16 snap/bootstrap pathology
       (a snapd.service start timeout, desktop-security-center
       configure-hook failure, a sanity timeout, ``RemoveSnapServices``
       beginning, ``/snap/snapd/current`` going missing, a
       ``snapd.seeded`` failure) and exports one bounded diagnostic
       frame the FIRST time each signal is seen - now including the
       actual failed snap Change task graph (Objective B), narrow
       snapd.service state/journal context (Objective C), a best-effort
       last-progress-before-timeout reconstruction (Objective D), a
       narrow process snapshot (Objective E), and explicit ordering
       timestamps for the snapd/portal/desktop-security-center/
       snapd.hold sequence (Objectives F/G) - each is filled in only
       from what this run's own bounded journal window actually shows,
       never guessed;
    4. **S7.1R21, trigger reliability corrected S7.1R22**: watches for
       the first occurrence of each of three known
       ``Filesystem/_probe/probe_once`` storage-probe failure signals
       (``probe_once``+``cancelled`` together, ``block_probe_fail``,
       ``disk_probe_fail`` - the exact real S7.1R20 forensic findings)
       and exports one bounded ``SEREIN STORAGE PROBE FRAME`` the
       first time each is seen - bounded, allowlisted excerpts of real
       installer-internal logs (``/var/log/installer/ubuntu_bootstrap.log``,
       confirmed present in real S7.1R20 evidence;
       ``subiquity-server-debug.log``/``curtin-install.log``, checked
       but never assumed present), read-only device topology/identity
       (``lsblk``, ``udevadm`` properties - never relies on
       ``/dev/vda``/``/dev/vdb`` ordering alone, since serial/udev
       properties let a HOST-SIDE extractor classify
       PROTECTED/TARGET/INSTALL_MEDIA/OTHER later), a read-only
       process snapshot filtered to storage-tool argv
       (probert/subiquity/blkid/lsblk/parted/udevadm/udisks/
       os-prober/grub-probe), a wider dedicated journal window
       filtered to storage-relevant keywords (never the same narrow
       200-line window used for snap-signal DETECTION - the real R20
       failure window spans minutes of unrelated desktop-session
       noise), and a dedicated udisks2 context section (journal lines,
       active udisks processes, vd*-device mount state) to test the
       S7.1R20 H2 hypothesis (udisks2 automount interference) without
       disabling/masking/stopping udisks2 or changing its policy in
       any way. This is instrumentation only - it does not, and
       cannot, prove root cause by itself; it exists so a future real
       run's own captured evidence can.

       **S7.1R22 trigger-detection corrective**: real S7.1R21-TCG-REPRO-1
       evidence proved the ORIGINAL trigger-DETECTION mechanism (all
       three signals checked against the SAME shared, snap-signal
       ``recent_journal`` 200-line snapshot) is genuinely unreliable -
       ``probe_once``+``cancelled`` and ``block_probe_fail`` both
       demonstrably occurred in that real run, yet
       ``storage_probe_frame_count`` stayed 0, because unrelated
       journal volume between one 10s poll and the next can scroll the
       real trigger line out of a fixed last-200-line window before
       the watcher ever inspects it. Two independent, structural fixes
       replace it, never merely a larger ``-n`` bound (which only
       widens the same race, it does not remove it):

       - ``block_probe_fail`` now fires directly from the SAME
         ``/var/crash/*block_probe_fail*.crash`` file scan this
         watcher already performs for the pre-existing crash-evidence
         capture - a crash file's mere EXISTENCE is a real, durable,
         journal-volume-proof signal regardless of how much unrelated
         journal noise followed it, under its own independent dedup
         key (``storage:block_probe_fail``, distinct from the
         filename-keyed dedup the existing crash-evidence capture
         already uses, so neither mechanism starves the other).
       - ``probe_once``+``cancelled`` and ``disk_probe_fail`` now use
         a dedicated, PER-POLL ``journalctl --after-cursor`` batch
         (only entries genuinely new since the previous poll) when
         this guest's journalctl supports cursor mode - verified once
         at watcher startup, never assumed - so unrelated journal
         volume can no longer evict a trigger line before this watcher
         inspects it. If cursor mode is unavailable/fails, detection
         falls back to a dedicated, explicitly weaker bounded window
         (``MAX_STORAGE_DETECTION_LINES``/``MAX_STORAGE_DETECTION_BYTES``
         - independent of the shared snap-signal window, so at least
         does not inherit ITS unrelated volatility either), and the
         frame records which mode actually fired it
         (``trigger_source=journal_cursor|bounded_window_fallback|crash_file``)
         so this is never silently assumed reliable. ``probe_once``
         and ``cancelled`` must now co-occur on the SAME journal line
         to count (real evidence confirms Subiquity emits both
         substrings on one line) - never a same-buffer,
         possibly-different-line match, which risked a false positive
         from two unrelated events.

       This round corrects the SENSOR only - it does not, and must
       not, change Subiquity/curtin storage behavior, udisks policy,
       or any timeout; the underlying storage pathology this sensor
       observes remains unfixed and is out of scope here.

    S7.1R16 Objective A: this watcher is no longer launched via
    Subiquity autoinstall early-commands (real Run #15/#16 evidence
    proved Subiquity does not even reach early-commands until WELL
    after the pathology has already recovered - Run #16's own
    autoinstall extraction/load occurred at ~4259s/~4266s, entirely
    after the ~446s-4193s snap pathology window). It is instead started
    independently of Subiquity, during live-session boot itself, via a
    QA-only kernel command-line token
    (``serein.installer.isoprep``'s own ``systemd.run=`` wiring) -
    exactly the same "kernel-parameter-only, zero squashfs
    modification" mechanism this project has used since R3's
    ``autoinstall`` token, R5's journald-forwarding, R7's debug
    logging, and R9's firmware-notifier mask. Whether the real Ubuntu
    live environment's systemd actually honors ``systemd.run=`` at a
    point early enough to precede the first snapd failure is NOT
    provable from this development environment (no real QEMU/Subiquity
    here) - the boot marker above is the mechanism by which a real run
    proves or disproves it, never assumed.

    Both evidence kinds are exported through the same QA-only,
    structurally one-way virtio-serial port ``run-qa-install.sh`` wires
    up (``QA_EVIDENCE_PORT_PATH``) - observation only, in both
    directions: this watcher never intentionally triggers either
    pathology, and never takes any corrective action of its own (never
    restarts snapd, never retries/acknowledges a snap Change, never
    mutates snap state, never installs/removes a snap).

    Guest-side contract (Section 6/12's absolute requirements, all held
    by construction here, never by convention):

    - reads ONLY ``/var/crash/*block_probe_fail*.crash``, the guest's
      own local systemd journal/snap/process state (via
      ``journalctl``/``snap``/``systemctl``/``ps``), and - S7.1R21 -
      a small, fixed, explicitly allowlisted family of files under
      ``/var/log/installer/`` plus ``lsblk``/``udevadm`` device
      topology/identity output, run against the guest's OWN state,
      never any host resource - never any host path, never any other
      guest path, and NEVER a recursive/arbitrary export of
      ``/var/log`` or any other directory;
    - writes ONLY to the named virtio-serial port - never any other
      file, device, or network socket;
    - never executes a host command, never opens a network connection,
      never accepts input FROM the port (the port is opened purely for
      appending);
    - finite and self-terminating: a fixed ``MAX_ITERATIONS``-step
      loop, never ``while true`` - it exits on its own well before the
      host's own QEMU timeout, rather than depending on the guest ever
      shutting down gracefully;
    - bounded: at most ``MAX_CRASH_FILES`` distinct crash files, at
      most ``MAX_SNAP_FRAMES`` distinct snap-pathology frames, and -
      S7.1R21 - at most ``MAX_STORAGE_FRAMES`` distinct storage-probe
      frames are ever exported, each capped at its own per-item byte
      limit, under one shared ``MAX_TOTAL_EVIDENCE_BYTES`` ceiling; at
      most ``MAX_FAILED_CHANGE_IDS`` failed-Change task graphs are ever
      captured per frame, never hardcoded to Change ID 1 - every
      truncation is recorded explicitly (``truncated=true``/``false``),
      never silent;
    - deduplicated: an in-memory ``seen`` list keyed by crash filename,
      ``snap:<trigger>``, or - S7.1R21 - ``storage:<trigger>``, so the
      same crash file or the same snap/storage signal is exported at
      most once per run, even though the watcher polls repeatedly;
    - a failing diagnostic command (``snap``/``systemctl``/
      ``journalctl``/``ps`` unavailable, or erroring) reads as
      ``NOT_OBSERVED`` and never aborts the watcher (no ``set -e``) -
      forensic failure is always secondary, never promoted to installer
      primary failure.
    """
    lines = [
        "#!/bin/sh",
        "set -u",
        # S7.1R22 Section 14 test affordance only (same pattern as
        # MAX_ITERATIONS/SLEEP_SECONDS below): a real run never sets
        # these env vars, so production PORT/crash-glob-dir are
        # unchanged - but a watcher-level test can point both at a
        # plain temp file/dir instead of the real QEMU virtio-serial
        # port and /var/crash.
        'PORT="${SEREIN_TEST_PORT:-' + QA_EVIDENCE_PORT_PATH + '}"',
        'CRASH_GLOB_DIR="${SEREIN_TEST_CRASH_DIR:-/var/crash}"',
        f"MAX_CRASH_FILES={QA_EVIDENCE_MAX_CRASH_FILES}",
        f"MAX_BYTES_PER_CRASH={QA_EVIDENCE_MAX_BYTES_PER_CRASH}",
        f"MAX_SNAP_FRAMES={QA_EVIDENCE_MAX_SNAP_FRAMES}",
        f"MAX_BYTES_PER_SNAP_FRAME={QA_EVIDENCE_MAX_BYTES_PER_SNAP_FRAME}",
        f"MAX_FAILED_CHANGE_IDS={QA_EVIDENCE_MAX_FAILED_CHANGE_IDS}",
        f"MAX_STORAGE_FRAMES={QA_EVIDENCE_MAX_STORAGE_FRAMES}",
        f"MAX_BYTES_PER_STORAGE_FRAME={QA_EVIDENCE_MAX_BYTES_PER_STORAGE_FRAME}",
        f"MAX_TOTAL_EVIDENCE_BYTES={QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES}",
        # S7.1R22 Section 14 test affordance only: a real run never
        # sets these env vars, so production behavior (the literal
        # constants below) is unchanged - but a watcher-level test can
        # now run the actual generated script end-to-end in a handful
        # of iterations instead of the real ~6600s ceiling.
        'MAX_ITERATIONS="${SEREIN_QA_WATCHER_MAX_ITERATIONS:-'
        f'{QA_EVIDENCE_WATCHER_MAX_ITERATIONS}}}"',
        'SLEEP_SECONDS="${SEREIN_QA_WATCHER_SLEEP_SECONDS:-'
        f'{QA_EVIDENCE_WATCHER_SLEEP_SECONDS}}}"',
        f"MAX_STORAGE_DETECTION_LINES={QA_EVIDENCE_MAX_STORAGE_DETECTION_LINES}",
        f"MAX_STORAGE_DETECTION_BYTES={QA_EVIDENCE_MAX_STORAGE_DETECTION_BYTES}",
        'seen=""',
        "exported_count=0",
        "snap_frame_count=0",
        "storage_frame_count=0",
        "total_bytes=0",
        "i=0",
        "",
        "# S7.1R16 Section 8: order-independent AND-chain timestamp",
        "# lookup against the CURRENT journal window - never a single",
        "# combined regex (a real message may put its tokens in either",
        "# order). Returns the first monotonic timestamp among matching",
        "# lines, or nothing if none match (caller defaults to",
        "# NOT_OBSERVED) - never guessed.",
        "_ts_for_all() {",
        '    acc="$recent_journal"',
        '    for pat in "$@"; do',
        '        acc=$(printf "%s\\n" "$acc" | grep -Ei -- "$pat") || acc=""',
        '        [ -n "$acc" ] || { printf "%s" ""; return 0; }',
        "    done",
        '    printf "%s\\n" "$acc" | head -n1 | '
        'sed -nE "s/^\\[[[:space:]]*([0-9]+\\.[0-9]+)\\].*/\\1/p"',
        "}",
        "",
        "# S7.1R16 Objective D: best-effort reconstruction of the last",
        "# snapd-tagged journal line seen before the FIRST timeout-style",
        "# message in the current window - never claims this proves a",
        "# deadlock, purely a bounded observation.",
        "_last_snapd_progress() {",
        '    printf "%s\\n" "$recent_journal" | awk \'',
        '        BEGIN { last_line = ""; last_ts = ""; timeout_ts = ""; found = 0 }',
        "        {",
        '            ts = ""',
        '            if (match($0, /\\[[ \\t]*[0-9]+\\.[0-9]+\\]/)) {',
        "                ts = substr($0, RSTART, RLENGTH); gsub(/[^0-9.]/, \"\", ts)",
        "            }",
        "            line_lc = tolower($0)",
        '            if (!found && (line_lc ~ /timed out/ || line_lc ~ /timeout/)) {',
        "                found = 1; timeout_ts = ts",
        "            }",
        '            if (!found && line_lc ~ /snapd/ && ts != "") { last_line = $0; last_ts = ts }',
        "        }",
        "        END {",
        '            if (last_line == "") { '
        'print "last_snapd_message_before_timeout=NOT_OBSERVED" }',
        '            else { gsub(/\\n/, " ", last_line)',
        '                   print "last_snapd_message_before_timeout=" last_line }',
        '            if (last_ts == "") { print "last_snapd_message_timestamp=NOT_OBSERVED" }',
        '            else { print "last_snapd_message_timestamp=" last_ts }',
        '            if (last_ts != "" && timeout_ts != "") {',
        '                print "time_from_last_snapd_message_to_timeout=" (timeout_ts - last_ts)',
        "            } else {",
        '                print "time_from_last_snapd_message_to_timeout=NOT_OBSERVED"',
        "            }",
        "        }",
        "    '",
        "}",
        "",
        "# S7.1R21 storage probe internal-evidence instrumentation,",
        "# trigger metadata added S7.1R22: captures one bounded SEREIN",
        "# STORAGE PROBE FRAME for the given trigger name ($1). Called",
        "# at most once per trigger (caller already deduplicates via",
        "# $seen before calling), and only while storage_frame_count <",
        "# MAX_STORAGE_FRAMES. Observation only - never mounts, signals,",
        "# kills, restarts, or writes installer state; a failing",
        "# diagnostic command reads as NOT_OBSERVED and never aborts the",
        "# watcher.",
        "#",
        "# S7.1R22 Section 9: $2 (trigger_source) and $3",
        "# (trigger_event_timestamp) are distinct facts from this",
        "# frame's own capture-time $s_ts - a durable crash-file trigger",
        "# may legitimately have no real original-failure timestamp",
        "# available (trigger_event_timestamp=NOT_OBSERVED), which is",
        "# never fabricated from the unrelated frame-capture moment.",
        "_emit_storage_frame() {",
        '    s_trigger="$1"',
        '    s_source="${2:-NOT_OBSERVED}"',
        '    s_event_ts="${3:-NOT_OBSERVED}"',
        '    [ -z "$s_event_ts" ] && s_event_ts="NOT_OBSERVED"',
        "    storage_frame_count=$((storage_frame_count + 1))",
        '    s_ts=$(cut -d" " -f1 /proc/uptime 2>/dev/null || echo "")',
        '    [ -z "$s_ts" ] && s_ts="NOT_OBSERVED"',
        "",
        "    # Section 7: bounded, allowlisted installer-log excerpts",
        "    # only - a small fixed list, each existence-checked first,",
        "    # never assumed, never a whole-file export. Only",
        "    # /var/log/installer/ubuntu_bootstrap.log was confirmed",
        "    # present in real S7.1R20 guest evidence - the other two",
        "    # are well-known standard Subiquity/curtin log names,",
        "    # checked the same defensive way, never assumed.",
        "    s_storage_grep="
        "'Filesystem|_probe|probe_once|probert|block_probe|disk_probe|"
        "restricted|udev|blkid|parted|lsblk|device|timeout|cancel|"
        "exception|traceback'",
        '    s_log_bootstrap="NOT_OBSERVED"',
        "    if [ -r /var/log/installer/ubuntu_bootstrap.log ]; then",
        '        s_log_bootstrap=$(grep -iE "$s_storage_grep" '
        "/var/log/installer/ubuntu_bootstrap.log 2>/dev/null | tail -n 60)",
        '        [ -z "$s_log_bootstrap" ] && s_log_bootstrap="NOT_OBSERVED"',
        "    fi",
        '    s_log_subiquity_debug="NOT_OBSERVED"',
        "    if [ -r /var/log/installer/subiquity-server-debug.log ]; then",
        '        s_log_subiquity_debug=$(grep -iE "$s_storage_grep" '
        "/var/log/installer/subiquity-server-debug.log 2>/dev/null | tail -n 60)",
        '        [ -z "$s_log_subiquity_debug" ] && s_log_subiquity_debug="NOT_OBSERVED"',
        "    fi",
        '    s_log_curtin="NOT_OBSERVED"',
        "    if [ -r /var/log/installer/curtin-install.log ]; then",
        "        s_log_curtin=$(grep -iE "
        "'block_probe|disk_probe|device|timeout|cancel|exception|traceback' "
        "/var/log/installer/curtin-install.log 2>/dev/null | tail -n 40)",
        '        [ -z "$s_log_curtin" ] && s_log_curtin="NOT_OBSERVED"',
        "    fi",
        "",
        "    # Section 8: read-only device topology/identity - never",
        "    # mounts, never modifies. Serial/udev properties let a",
        "    # HOST-SIDE extractor classify",
        "    # PROTECTED/TARGET/INSTALL_MEDIA/OTHER later, never this",
        "    # watcher itself, and never by guest device-path ordering alone.",
        "    s_lsblk=$(lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,RO,SERIAL 2>/dev/null)",
        '    [ -z "$s_lsblk" ] && s_lsblk="NOT_OBSERVED"',
        '    s_udev_props="NOT_OBSERVED"',
        "    if command -v udevadm >/dev/null 2>&1; then",
        "        s_udev_props=$(",
        "            for d in /sys/block/vd* /sys/block/sr*; do",
        '                [ -e "$d" ] || continue',
        '                dn=$(basename "$d")',
        '                udevadm info --query=property --name="/dev/$dn" 2>/dev/null | '
        "grep -E '^(DEVNAME|ID_SERIAL|ID_SERIAL_SHORT|ID_MODEL|ID_BUS)='",
        "            done",
        "        )",
        '        [ -z "$s_udev_props" ] && s_udev_props="NOT_OBSERVED"',
        "    fi",
        "",
        "    # Section 9: one bounded, read-only process snapshot - no",
        "    # signal, no kill, no ptrace, no state change of any kind.",
        "    s_procs=$(ps -eo pid,ppid,stat,etime,args 2>/dev/null | grep -iE "
        "'probert|subiquity|blkid|lsblk|parted|udevadm|udisks|os-prober|grub-probe' | "
        "grep -v 'grep -')",
        '    [ -z "$s_procs" ] && s_procs="NOT_OBSERVED"',
        "",
        "    # Section 10: a wider, DEDICATED journal fetch (never the",
        "    # shared 200-line snap-detection window alone) filtered to",
        "    # storage-relevant keywords only.",
        "    s_journal_wide=$(journalctl --no-pager -o short-monotonic -n 1000 2>/dev/null) "
        '|| s_journal_wide=""',
        '    s_journal_window="NOT_OBSERVED"',
        '    if [ -n "$s_journal_wide" ]; then',
        '        s_journal_window=$(printf "%s" "$s_journal_wide" | grep -iE '
        "'subiquity|Filesystem|probe_once|probert|block_probe|disk_probe|udisks|udev|"
        "blkid|parted' | tail -n 80)",
        '        [ -z "$s_journal_window" ] && s_journal_window="NOT_OBSERVED"',
        "    fi",
        "",
        "    # Section 11 (H2 falsification/support): udisks-specific",
        "    # context only - never disables/masks/stops udisks, never",
        "    # changes automount policy, observation only.",
        '    s_udisks_journal="NOT_OBSERVED"',
        '    if [ -n "$s_journal_wide" ]; then',
        '        s_udisks_journal=$(printf "%s" "$s_journal_wide" | grep -iE '
        "'udisks|automount' | tail -n 40)",
        '        [ -z "$s_udisks_journal" ] && s_udisks_journal="NOT_OBSERVED"',
        "    fi",
        "    s_udisks_procs=$(ps -eo pid,ppid,stat,etime,args 2>/dev/null | grep -i 'udisks' "
        "| grep -v 'grep ')",
        '    [ -z "$s_udisks_procs" ] && s_udisks_procs="NOT_OBSERVED"',
        "    s_mount_state=$(mount 2>/dev/null | grep -E 'vda|vdb')",
        '    [ -z "$s_mount_state" ] && s_mount_state="NOT_OBSERVED"',
        "",
        "    # Section 6/13: header fields + per-item bound with an",
        "    # honest truncated= flag - the body is sized BEFORE the",
        "    # header is finalized so the flag is never wrong.",
        "    s_header_budget=200",
        "    s_body_budget=$((MAX_BYTES_PER_STORAGE_FRAME - s_header_budget))",
        '    [ "$s_body_budget" -lt 0 ] && s_body_budget=0',
        "    s_body=$(",
        '        echo "[INSTALLER_LOG_UBUNTU_BOOTSTRAP]"; echo "$s_log_bootstrap"',
        '        echo ""',
        '        echo "[INSTALLER_LOG_SUBIQUITY_SERVER_DEBUG]"; echo "$s_log_subiquity_debug"',
        '        echo ""',
        '        echo "[INSTALLER_LOG_CURTIN_INSTALL]"; echo "$s_log_curtin"',
        '        echo ""',
        '        echo "[DEVICE_TOPOLOGY_LSBLK]"; echo "$s_lsblk"',
        '        echo ""',
        '        echo "[DEVICE_UDEV_PROPERTIES]"; echo "$s_udev_props"',
        '        echo ""',
        '        echo "[PROCESS_SNAPSHOT]"; echo "$s_procs"',
        '        echo ""',
        '        echo "[STORAGE_JOURNAL_WINDOW]"; echo "$s_journal_window"',
        '        echo ""',
        '        echo "[UDISKS_JOURNAL_CONTEXT]"; echo "$s_udisks_journal"',
        '        echo ""',
        '        echo "[UDISKS_PROCESS_SNAPSHOT]"; echo "$s_udisks_procs"',
        '        echo ""',
        '        echo "[MOUNT_STATE_VD_DEVICES]"; echo "$s_mount_state"',
        "    )",
        '    s_body_full_len=${#s_body}',
        '    s_frame_trunc="false"',
        '    if [ "$s_body_full_len" -gt "$s_body_budget" ]; then',
        '        s_body=$(printf "%s" "$s_body" | head -c "$s_body_budget")',
        '        s_frame_trunc="true"',
        "    fi",
        "    s_frame=$(",
        '        echo "=== SEREIN STORAGE PROBE FRAME ==="',
        '        echo "frame_sequence=$storage_frame_count"',
        '        echo "trigger=$s_trigger"',
        '        echo "timestamp=$s_ts"',
        '        echo "frame_capture_timestamp=$s_ts"',
        '        echo "trigger_source=$s_source"',
        '        echo "trigger_event_timestamp=$s_event_ts"',
        '        echo "truncated=$s_frame_trunc"',
        '        echo ""',
        '        printf "%s" "$s_body"',
        '        echo ""',
        '        echo "=== END STORAGE PROBE FRAME ==="',
        "    )",
        '    s_flen=${#s_frame}',
        "    remaining=$((MAX_TOTAL_EVIDENCE_BYTES - total_bytes))",
        '    if [ "$remaining" -gt 0 ] && [ -e "$PORT" ] && [ -w "$PORT" ]; then',
        '        [ "$s_flen" -gt "$remaining" ] && s_frame=$(printf "%s" "$s_frame" | '
        'head -c "$remaining") && s_flen="$remaining"',
        "        # A trailing newline is always appended here (never part of",
        "        # the byte-capped $s_frame itself) so two consecutive",
        "        # frames can never run together onto the same line - the",
        "        # host-side extractor's own ^=== ... ===$ anchored match",
        "        # depends on this separator existing unconditionally.",
        '        printf "%s\\n" "$s_frame" >> "$PORT" 2>/dev/null || true',
        "        total_bytes=$((total_bytes + s_flen + 1))",
        "    fi",
        "}",
        "",
        "# S7.1R16 Objective A/8: the boot marker - written ONCE, before",
        "# anything else, so a real run's own monotonic timestamp is the",
        "# proof (or disproof) that this watcher actually started before",
        "# the first snapd failure - never merely inferred from this",
        "# mechanism existing in source code.",
        'if [ -e "$PORT" ] && [ -w "$PORT" ]; then',
        '    boot_ts=$(cut -d" " -f1 /proc/uptime 2>/dev/null || echo "")',
        "    {",
        '        echo "SEREIN_EVIDENCE_WATCHER_STARTED"',
        '        echo "watcher_start_monotonic_ts=$boot_ts"',
        '    } >> "$PORT" 2>/dev/null || true',
        '    boot_ts_len=${#boot_ts}',
        "    total_bytes=$((total_bytes + boot_ts_len + 48))",
        "fi",
        "",
        "# S7.1R22: establish a per-poll storage-journal cursor if this",
        "# guest's journalctl actually supports --show-cursor/",
        "# --after-cursor - verified here, once, never assumed (Section",
        "# 6 of the R22 corrective). probe_once+cancelled/disk_probe_fail",
        "# detection below then only ever scans entries genuinely NEW",
        "# since the previous poll, so unrelated journal volume can",
        "# never again silently evict a real trigger line before this",
        "# watcher checks it (the real R21-TCG-REPRO-1 defect). A",
        "# failure here is diagnostic-only and never aborts the",
        "# watcher - STORAGE_TRIGGER_MODE simply stays the explicitly",
        "# weaker bounded-window fallback.",
        'storage_cursor=""',
        'STORAGE_TRIGGER_MODE="bounded_window_fallback"',
        '_cursor_probe=$(journalctl --no-pager -n 0 --show-cursor 2>/dev/null)',
        'if [ -n "$_cursor_probe" ]; then',
        '    _probe_cursor=$(printf "%s\\n" "$_cursor_probe" | '
        'sed -n "s/^-- cursor: //p" | tail -n1)',
        '    if [ -n "$_probe_cursor" ]; then',
        '        storage_cursor="$_probe_cursor"',
        '        STORAGE_TRIGGER_MODE="journal_cursor"',
        "    fi",
        "fi",
        "",
        'while [ "$i" -lt "$MAX_ITERATIONS" ]; do',
        '    if [ -e "$PORT" ] && [ -w "$PORT" ]; then',
        '        for f in "$CRASH_GLOB_DIR"/*block_probe_fail*.crash; do',
        '            [ -e "$f" ] || continue',
        '            case " $seen " in',
        '                *" $f "*) continue ;;',
        "            esac",
        '            seen="$seen $f"',
        "",
        "            # S7.1R22 Section 5A/8: a durable,",
        "            # journal-volume-proof direct trigger - this crash",
        "            # file's mere EXISTENCE is real regardless of how",
        "            # much journal noise followed it. An INDEPENDENT",
        "            # dedup key from the filename-keyed $seen entry",
        "            # just above (fires once total per run, not once",
        "            # per crash file), so neither this nor the",
        "            # existing per-file crash-evidence capture below",
        "            # starves the other.",
        '            if [ "$storage_frame_count" -lt "$MAX_STORAGE_FRAMES" ]; then',
        '                case " $seen " in',
        '                    *" storage:block_probe_fail "*) ;;',
        "                    *)",
        '                        seen="$seen storage:block_probe_fail"',
        "                        _emit_storage_frame block_probe_fail crash_file "
        "NOT_OBSERVED",
        "                        ;;",
        "                esac",
        "            fi",
        "",
        '            [ "$exported_count" -ge "$MAX_CRASH_FILES" ] && continue',
        "            exported_count=$((exported_count + 1))",
        '            size=$(wc -c < "$f" 2>/dev/null || echo 0)',
        '            mtime=$(stat -c %Y "$f" 2>/dev/null || echo "")',
        "            sha256=$(sha256sum \"$f\" 2>/dev/null | cut -d' ' -f1)",
        '            take="$MAX_BYTES_PER_CRASH"',
        "            remaining=$((MAX_TOTAL_EVIDENCE_BYTES - total_bytes))",
        '            [ "$remaining" -lt "$take" ] && take="$remaining"',
        '            [ "$take" -le 0 ] && continue',
        '            trunc="false"',
        '            [ "$size" -gt "$take" ] && trunc="true"',
        "            {",
        '                echo "===BEGIN-CRASH-EVIDENCE==="',
        '                echo "filename=$(basename "$f")"',
        '                echo "size=$size"',
        '                echo "mtime=$mtime"',
        '                echo "sha256=$sha256"',
        '                echo "truncated=$trunc"',
        '                echo "---BEGIN-CONTENT---"',
        '                head -c "$take" "$f" 2>/dev/null',
        '                echo ""',
        '                echo "---END-CONTENT---"',
        '                echo "===END-CRASH-EVIDENCE==="',
        '            } >> "$PORT" 2>/dev/null || true',
        "            total_bytes=$((total_bytes + take))",
        "        done",
        "",
        "        # S7.1R15/R16: recurring snap/bootstrap pathology signals",
        "        # (Runs #7/#11/#12/#15/#16) - a single bounded journal",
        "        # fetch per iteration in monotonic-timestamp form (the",
        "        # SAME `[ NNN.NNNNNN]` convention every other host-side",
        "        # parser in this project already understands), checked",
        "        # against all six known signals, never a fresh",
        "        # journalctl invocation per signal (Section 11/12 - low",
        "        # overhead, secondary/non-blocking on failure).",
        '        recent_journal=$(journalctl --no-pager -o short-monotonic -n 200 '
        '2>/dev/null) || recent_journal=""',
        '        if [ -n "$recent_journal" ] && '
        '[ "$snap_frame_count" -lt "$MAX_SNAP_FRAMES" ]; then',
        '            trigger=""',
        '            key=""',
        '            if printf "%s" "$recent_journal" | grep -qi \'snapd.service\' && '
        'printf "%s" "$recent_journal" | grep -qiE \'start operation timed out|timed out\'; '
        'then',
        '                trigger="snapd_service_timeout"; key="snap:service_timeout"',
        '            elif printf "%s" "$recent_journal" | grep -qi \'desktop-security-center\' '
        '&& printf "%s" "$recent_journal" | grep -qiE \'hook|configure\' && '
        'printf "%s" "$recent_journal" | grep -qiE \'fail|error\'; then',
        '                trigger="desktop_security_center_hook_failure"; key="snap:hook_failure"',
        '            elif printf "%s" "$recent_journal" | grep -qi \'sanity timeout\'; then',
        '                trigger="sanity_timeout"; key="snap:sanity_timeout"',
        '            elif printf "%s" "$recent_journal" | grep -qi \'RemoveSnapServices\'; then',
        '                trigger="remove_snap_services"; key="snap:remove_services"',
        '            elif printf "%s" "$recent_journal" | grep -qi \'/snap/snapd/current\' && '
        'printf "%s" "$recent_journal" | grep -qiE \'missing|no such file\'; then',
        '                trigger="snapd_current_missing"; key="snap:current_missing"',
        '            elif printf "%s" "$recent_journal" | grep -qi \'snapd.seeded\' && '
        'printf "%s" "$recent_journal" | grep -qiE \'fail|Scheduled restart\'; then',
        '                trigger="snapd_seeded_failure"; key="snap:seeded_failure"',
        "            fi",
        '            if [ -n "$trigger" ]; then',
        '                case " $seen " in',
        '                    *" $key "*) trigger="" ;;',
        "                esac",
        "            fi",
        '            if [ -n "$trigger" ]; then',
        '                seen="$seen $key"',
        "                snap_frame_count=$((snap_frame_count + 1))",
        '                ts=$(cut -d" " -f1 /proc/uptime 2>/dev/null || echo "")',
        "",
        "                # S7.1R16 Objectives F/G: ordering timestamps -",
        "                # a plain observation of what THIS bounded",
        "                # journal window shows, never a causal claim.",
        '                hold_start_ts=$(_ts_for_all \'snapd\\.hold\' \'start\')',
        '                hold_finish_ts=$(_ts_for_all \'snapd\\.hold\' \'finish\')',
        '                portal_failure_ts=$(_ts_for_all \'portal\' \'timeout\')',
        '                dsc_failure_ts=$(_ts_for_all \'desktop-security-center\' \'fail\')',
        '                snapd_failure_ts=$(_ts_for_all \'snapd\' \'timeout|timed out\')',
        '                [ -z "$hold_start_ts" ] && hold_start_ts="NOT_OBSERVED"',
        '                [ -z "$hold_finish_ts" ] && hold_finish_ts="NOT_OBSERVED"',
        '                [ -z "$portal_failure_ts" ] && portal_failure_ts="NOT_OBSERVED"',
        '                [ -z "$dsc_failure_ts" ] && dsc_failure_ts="NOT_OBSERVED"',
        '                [ -z "$snapd_failure_ts" ] && snapd_failure_ts="NOT_OBSERVED"',
        "",
        '                snap_state=$(snap changes 2>/dev/null | head -n 20)',
        '                [ -z "$snap_state" ] && snap_state="NOT_OBSERVED"',
        "",
        "                # S7.1R16 Objective B: dynamic failed-Change",
        "                # discovery - never hardcoded to Change ID 1.",
        '                failed_change_tasks="NOT_OBSERVED"',
        '                if [ "$snap_state" != "NOT_OBSERVED" ]; then',
        '                    failed_ids=$(printf "%s\\n" "$snap_state" | '
        "awk 'NR>1 && $2 ~ /^[Ee]rror/ {print $1}')",
        '                    if [ -n "$failed_ids" ]; then',
        '                        fc_count=0',
        '                        failed_change_tasks=""',
        '                        for cid in $failed_ids; do',
        '                            [ "$fc_count" -ge "$MAX_FAILED_CHANGE_IDS" ] && break',
        "                            fc_count=$((fc_count + 1))",
        '                            task_out=$(snap tasks "$cid" 2>/dev/null)',
        '                            [ -z "$task_out" ] && task_out="NOT_OBSERVED"',
        '                            failed_change_tasks="$failed_change_tasks--- change '
        '$cid ---'
        '\n$task_out'
        '\n\n"',
        "                        done",
        "                    fi",
        "                fi",
        "",
        '                snapd_state=$(systemctl is-active snapd.service 2>/dev/null '
        '|| echo "NOT_OBSERVED")',
        "",
        "                # S7.1R16 Objective C: narrow snapd.service",
        "                # metadata + journal context.",
        '                snapd_props=$(systemctl show snapd.service --no-pager '
        '-p ActiveState -p SubState -p Result -p NRestarts -p ExecMainPID '
        '-p ExecMainCode -p ExecMainStatus -p ExecMainStartTimestampMonotonic '
        '-p ActiveEnterTimestampMonotonic -p InactiveEnterTimestampMonotonic '
        '-p TimeoutStartUSec 2>/dev/null)',
        '                [ -z "$snapd_props" ] && snapd_props="NOT_OBSERVED"',
        '                snapd_journal=$(journalctl -u snapd.service --no-pager '
        '-o short-monotonic -n 40 2>/dev/null)',
        '                [ -z "$snapd_journal" ] && snapd_journal="NOT_OBSERVED"',
        "",
        "                # S7.1R16 Objective D.",
        '                last_progress=$(_last_snapd_progress)',
        "",
        "                # S7.1R16 Objective E: a narrow, read-only",
        "                # process snapshot - no ptrace, no memory dump,",
        "                # no debugger attach, no scheduling change.",
        '                snapd_proc=$(ps -o pid,stat,etime,time -C snapd 2>/dev/null | '
        "awk 'NR==2')",
        '                [ -z "$snapd_proc" ] && snapd_proc="NOT_OBSERVED"',
        "",
        "                dsc_state=$(journalctl -u 'snap.desktop-security-center*' "
        '--no-pager -o short-monotonic -n 20 2>/dev/null)',
        '                [ -z "$dsc_state" ] && dsc_state="NOT_OBSERVED"',
        '                hold_state=$(systemctl show snapd.hold.service --no-pager '
        '-p ActiveState 2>/dev/null)',
        '                [ -z "$hold_state" ] && hold_state="NOT_OBSERVED"',
        "                portal_state=$(systemctl --user status 'xdg-desktop-portal*' "
        '--no-pager 2>/dev/null)',
        '                [ -z "$portal_state" ] && portal_state="NOT_OBSERVED"',
        '                if [ -e /snap/snapd/current ]; then',
        '                    snap_current=$(readlink -f /snap/snapd/current 2>/dev/null '
        '|| echo "PRESENT_UNREADABLE")',
        "                else",
        '                    snap_current="MISSING"',
        "                fi",
        '                journal_ctx=$(printf "%s" "$recent_journal" | '
        "grep -iE 'snapd|desktop-security-center|RemoveSnapServices' | tail -n 30)",
        '                [ -z "$journal_ctx" ] && journal_ctx="NOT_OBSERVED"',
        "",
        "                frame=$(",
        '                    echo "=== SEREIN SNAP FAILURE FRAME ==="',
        '                    echo "timestamp=$ts"',
        '                    echo "trigger=$trigger"',
        '                    echo "hold_start_ts=$hold_start_ts"',
        '                    echo "hold_finish_ts=$hold_finish_ts"',
        '                    echo "portal_failure_ts=$portal_failure_ts"',
        '                    echo "dsc_failure_ts=$dsc_failure_ts"',
        '                    echo "snapd_failure_ts=$snapd_failure_ts"',
        '                    echo ""',
        '                    echo "[SNAP_STATE]"; echo "$snap_state"',
        '                    echo ""',
        '                    echo "[FAILED_CHANGE_TASKS]"; echo "$failed_change_tasks"',
        '                    echo "[SNAPD]"; echo "$snapd_state"',
        '                    echo ""',
        '                    echo "[SNAPD_SERVICE_PROPERTIES]"; echo "$snapd_props"',
        '                    echo ""',
        '                    echo "[SNAPD_SERVICE_JOURNAL]"; echo "$snapd_journal"',
        '                    echo ""',
        '                    echo "[SNAPD_LAST_PROGRESS]"; echo "$last_progress"',
        '                    echo ""',
        '                    echo "[SNAPD_PROCESS_SNAPSHOT]"; echo "$snapd_proc"',
        '                    echo ""',
        '                    echo "[DESKTOP_SECURITY_CENTER]"; echo "$dsc_state"',
        '                    echo ""',
        '                    echo "[SNAPD_HOLD]"; echo "$hold_state"',
        '                    echo ""',
        '                    echo "[PORTAL_STATE]"; echo "$portal_state"',
        '                    echo ""',
        '                    echo "[SNAP_CURRENT]"; echo "$snap_current"',
        '                    echo ""',
        '                    echo "[JOURNAL_CONTEXT]"; echo "$journal_ctx"',
        '                    echo "=== END FRAME ==="',
        "                )",
        '                frame=$(printf "%s" "$frame" | head -c "$MAX_BYTES_PER_SNAP_FRAME")',
        '                flen=${#frame}',
        "                remaining=$((MAX_TOTAL_EVIDENCE_BYTES - total_bytes))",
        '                if [ "$remaining" -gt 0 ]; then',
        '                    [ "$flen" -gt "$remaining" ] && frame=$(printf "%s" "$frame" | '
        'head -c "$remaining") && flen="$remaining"',
        '                    printf "%s" "$frame" >> "$PORT" 2>/dev/null || true',
        "                    total_bytes=$((total_bytes + flen))",
        "                fi",
        "            fi",
        "        fi",
        "",
        "        # S7.1R22 storage-trigger reliability corrective:",
        "        # probe_once+cancelled and disk_probe_fail are now",
        "        # detected from a DEDICATED per-poll batch - NEVER the",
        "        # shared, volatile $recent_journal window used for",
        "        # snap-signal detection above (that window's own",
        "        # volatility is exactly what caused the real",
        "        # R21-TCG-REPRO-1 miss: a genuine trigger line scrolled",
        "        # out of the last-200-line snapshot between polls,",
        "        # before this watcher ever inspected it).",
        "        # block_probe_fail no longer depends on any journal",
        "        # window at all - it already fires directly from the",
        "        # crash-file scan above (Section 5A), a durable signal",
        "        # unaffected by journal volume entirely.",
        '        if [ "$STORAGE_TRIGGER_MODE" = "journal_cursor" ]; then',
        '            _storage_raw=$(journalctl --no-pager -o short-monotonic '
        '--after-cursor="$storage_cursor" --show-cursor 2>/dev/null)',
        '            if [ -n "$_storage_raw" ]; then',
        '                _new_cursor=$(printf "%s\\n" "$_storage_raw" | '
        'sed -n "s/^-- cursor: //p" | tail -n1)',
        '                [ -n "$_new_cursor" ] && storage_cursor="$_new_cursor"',
        '                storage_batch=$(printf "%s\\n" "$_storage_raw" | '
        'grep -v "^-- cursor: " | grep -v "^-- No entries --\\$" | '
        'head -c "$MAX_STORAGE_DETECTION_BYTES")',
        "            else",
        '                storage_batch=""',
        "            fi",
        "        else",
        '            storage_batch=$(journalctl --no-pager -o short-monotonic '
        '-n "$MAX_STORAGE_DETECTION_LINES" 2>/dev/null | '
        'head -c "$MAX_STORAGE_DETECTION_BYTES") || storage_batch=""',
        "        fi",
        '        if [ -n "$storage_batch" ] && '
        '[ "$storage_frame_count" -lt "$MAX_STORAGE_FRAMES" ]; then',
        "            # Section 7: probe_once and cancelled must co-occur",
        "            # on the SAME journal line to count (real evidence",
        "            # confirms Subiquity emits both substrings on one",
        "            # line) - piping one grep's already line-filtered",
        "            # output into a second grep keeps the match",
        "            # anchored to a single line, never a same-buffer,",
        "            # different-line false association.",
        '            _po_line=$(printf "%s\\n" "$storage_batch" | '
        'grep -i \'probe_once\' | grep -i \'cancelled\' | head -n1)',
        '            if [ "$storage_frame_count" -lt "$MAX_STORAGE_FRAMES" ] && '
        '[ -n "$_po_line" ]; then',
        '                case " $seen " in',
        '                    *" storage:probe_cancelled "*) ;;',
        "                    *)",
        '                        seen="$seen storage:probe_cancelled"',
        '                        _po_ts=$(printf "%s" "$_po_line" | '
        'sed -nE "s/^\\[[[:space:]]*([0-9]+\\.[0-9]+)\\].*/\\1/p")',
        '                        [ -z "$_po_ts" ] && _po_ts="NOT_OBSERVED"',
        '                        _emit_storage_frame probe_cancelled '
        '"$STORAGE_TRIGGER_MODE" "$_po_ts"',
        "                        ;;",
        "                esac",
        "            fi",
        '            _dp_line=$(printf "%s\\n" "$storage_batch" | '
        'grep -i \'disk_probe_fail\' | head -n1)',
        '            if [ "$storage_frame_count" -lt "$MAX_STORAGE_FRAMES" ] && '
        '[ -n "$_dp_line" ]; then',
        '                case " $seen " in',
        '                    *" storage:disk_probe_fail "*) ;;',
        "                    *)",
        '                        seen="$seen storage:disk_probe_fail"',
        '                        _dp_ts=$(printf "%s" "$_dp_line" | '
        'sed -nE "s/^\\[[[:space:]]*([0-9]+\\.[0-9]+)\\].*/\\1/p")',
        '                        [ -z "$_dp_ts" ] && _dp_ts="NOT_OBSERVED"',
        '                        _emit_storage_frame disk_probe_fail '
        '"$STORAGE_TRIGGER_MODE" "$_dp_ts"',
        "                        ;;",
        "                esac",
        "            fi",
        "        fi",
        "    fi",
        "    i=$((i + 1))",
        '    sleep "$SLEEP_SECONDS"',
        "done",
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def build_qa_evidence_launcher_script() -> str:
    """S7.1R17 (internal handoff logic unchanged by S7.1R19): the
    short-lived boot launcher that hands the long-running watcher
    (:func:`build_qa_evidence_watcher_script`) off to systemd as an
    independent, PID1-managed transient unit, then exits almost
    immediately.

    **The real Run #17 defect this corrects**: S7.1R16 pointed the
    ``systemd.run=`` kernel token directly at the long-running watcher
    script. Real Run #17 evidence (RUN_ID=34784265045) proved this
    caused ``kernel-command-line.service`` (the unit
    ``systemd-run-generator`` synthesizes for a ``systemd.run=`` token)
    to remain in its "start job running" state for the watcher's ENTIRE
    ~6600s bounded lifetime - blocking every unit ordered after it
    (snapd never started, autoinstall never started) until the host's
    own 6600s QEMU timeout killed the run. ``SEREIN_EVIDENCE_WATCHER_STARTED``
    WAS observed at ~280.86s, proving the watcher itself started early
    enough - the defect was purely in HOW it was launched, never in the
    watcher's own logic (Objectives B-G, block-probe watching, etc. are
    all unchanged this round).

    **The internal handoff mechanism** (unchanged since R17, and again
    this round - see :func:`_qa_evidence_launcher_early_command` for
    what DID change): runs `systemd-run --no-block --collect` (a real,
    documented systemd client command, never a raw shell `&` background
    job - a backgrounded child of a parent process's own cgroup is
    liable to be killed the instant that parent exits/is torn down,
    per systemd's default ``KillMode=control-group``; a `systemd-run`
    transient unit is a genuinely SEPARATE unit/cgroup PID1 manages
    directly, immune to the launcher's own lifecycle) to start the
    watcher as ``serein-qa-evidence-watcher.service`` - a unit this
    launcher never waits on (``--no-block`` returns the instant the job
    is QUEUED, not once the watcher finishes) and never links into any
    other unit's dependency graph (no ``Before=``/``Requires=``/
    ``Wants=`` naming snapd or any other target anywhere in this
    codebase - the watcher OBSERVES snapd, it never gates it).
    ``--collect`` tells systemd to automatically unload the transient
    unit once it exits, so it never lingers as a permanently "failed"/
    "inactive" unit cluttering the live session's own unit list.

    **S7.1R19 correction - how this script is now TRIGGERED**: R16-R18
    triggered this script via a `systemd.run=` kernel command-line
    token. Real Run #19 evidence (RUN_ID=34832918752) proved that, even
    after R18's fix eliminated the early-shutdown defect
    (`SEREIN_EVIDENCE_LAUNCHER_STARTED`/`_COMPLETED` were both observed,
    ~275.99s/~277.80s, and the guest correctly stayed ALIVE afterward),
    the mere PRESENCE of `systemd.run=` on the kernel command line still
    prevented the REST of the normal live-session boot graph from ever
    starting - `kernel-command-line.target` was reached and systemd
    reported startup FINISHED at ~277.88s, with
    snapd.service/snapd.seeded/Subiquity/autoinstall all subsequently
    NOT_OBSERVED before the 6600s host timeout. The most likely
    mechanism (INFERRED from `systemd-run-generator`'s own documented
    purpose - "run a single command instead of the usual set of
    services during boot" - and from the observed symptom pattern,
    never independently verified against a real boot-graph dump in this
    development environment) is that the generator retargets this
    boot's effective default target rather than merely adding an
    ADDITIONAL peer dependency alongside the normal one. Regardless of
    the exact internal mechanism, the real, PROVEN correlation (with
    `systemd.run=` present, the normal live-session services never
    start; every historical run before R16 introduced it eventually DID
    reach them) is sufficient justification to retire it. This script
    (and its own internal `systemd-run` handoff to the watcher, which
    is unaffected by this change and remains exactly as described
    above) is now invoked from Subiquity's own ``early-commands``
    autoinstall directive instead - see
    :func:`_qa_evidence_launcher_early_command`'s own docstring for the
    full rationale, including the real, project-established tooling
    constraint (no squashfs-modification capability) that ruled out a
    persisted, boot-graph-integrated systemd unit as this round's fix.

    Emits ``SEREIN_EVIDENCE_LAUNCHER_STARTED``/
    ``SEREIN_EVIDENCE_LAUNCHER_COMPLETED`` markers (with monotonic
    timestamps) bracketing the ``systemd-run`` call - a real run's own
    ``launcher_finish_ts - launcher_start_ts`` is the real proof this
    launcher completes quickly, never merely asserted from this
    script's own source. **Caveat honestly carried forward**: whether
    ``systemd-run`` can reach PID1's manager socket at whatever point
    Subiquity's own early-commands stage actually runs is NOT validated
    in this development environment (no real QEMU/live-ISO boot here) -
    if it cannot, `systemd-run` simply fails (non-fatal, `|| true`) and
    the watcher never starts, which is itself real, honest, observable
    evidence for a real run rather than a silent hang.
    """
    lines = [
        "#!/bin/sh",
        "set -u",
        f'PORT="{QA_EVIDENCE_PORT_PATH}"',
        f'WATCHER_UNIT="{QA_EVIDENCE_WATCHER_UNIT_NAME}"',
        f'WATCHER_SCRIPT="/cdrom/{QA_EVIDENCE_WATCHER_ISO_FILENAME}"',
        "",
        'if [ -e "$PORT" ] && [ -w "$PORT" ]; then',
        '    launcher_start_ts=$(cut -d" " -f1 /proc/uptime 2>/dev/null || echo "")',
        "    {",
        '        echo "SEREIN_EVIDENCE_LAUNCHER_STARTED"',
        '        echo "launcher_start_ts=$launcher_start_ts"',
        '    } >> "$PORT" 2>/dev/null || true',
        "fi",
        "",
        "# S7.1R17 Objective A: hand the long-running watcher off to a",
        "# genuinely independent, PID1-managed transient unit - never a",
        "# plain shell `&` background job (killed with this launcher's",
        "# own cgroup under systemd's default KillMode=control-group).",
        "# --no-block: return the instant the job is QUEUED, never wait",
        "# for the watcher itself to run or finish. --collect: auto-unload",
        "# the transient unit once it exits, never left lingering.",
        "systemd-run --no-block --collect \\",
        '    --unit="$WATCHER_UNIT" \\',
        '    --description="Serein QA evidence watcher (observation only)" \\',
        '    /bin/sh "$WATCHER_SCRIPT" >/dev/null 2>&1 || true',
        "",
        'if [ -e "$PORT" ] && [ -w "$PORT" ]; then',
        '    launcher_finish_ts=$(cut -d" " -f1 /proc/uptime 2>/dev/null || echo "")',
        "    {",
        '        echo "SEREIN_EVIDENCE_LAUNCHER_COMPLETED"',
        '        echo "launcher_finish_ts=$launcher_finish_ts"',
        '    } >> "$PORT" 2>/dev/null || true',
        "fi",
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def _qa_evidence_launcher_early_command() -> str:
    """S7.1R19 corrective: one ``early-commands`` shell one-liner that
    base64-decodes and launches :func:`build_qa_evidence_launcher_script`
    detached in the background - reusing verbatim this project's own
    ORIGINAL S7.1R14 idiom (the same base64-round-trip discipline
    ``_install_state_late_command`` still uses for ``late-commands``),
    which was the QA evidence channel's very first launch mechanism
    before R16 moved away from it.

    **Why this round returns to early-commands** (the full history is
    also recorded in ``docs/installer/known-limitations.md``'s own
    S7.1R19 entry): S7.1R16 moved the launch trigger OFF early-commands
    specifically to observe snapd's own startup in real time - Subiquity
    itself ships as a snap, so it structurally cannot even begin running
    (let alone reach its own early-commands stage) until AFTER snapd has
    already seeded, a real dependency this project's own code cannot
    route around. R16-R18 progressively tried a `systemd.run=` kernel
    command-line token instead. Real Run #19 evidence (RUN_ID=34832918752)
    proved that even after R18 fixed the early-shutdown defect (the
    launcher itself completed correctly, ~275.99s-~277.80s, and the
    guest correctly stayed ALIVE afterward), `systemd.run=`'s mere
    presence still prevents the REST of the normal live-session boot
    graph (snapd, Subiquity, everything) from ever starting - see
    :func:`build_qa_evidence_launcher_script`'s own docstring for the
    full observed-evidence/inferred-mechanism breakdown.

    A real, persisted, boot-graph-integrated QA-only systemd unit (the
    architecturally PREFERRED fix, which would let the watcher start
    from a normal early target like ``sysinit.target`` without gating
    or being gated by snapd) would need a real unit FILE placed
    somewhere systemd's unit loader searches (e.g.
    ``/etc/systemd/system/``) early enough for a `systemd.wants=<unit>`
    kernel token to resolve it. This project has NO squashfs-
    modification tooling (no ``unsquashfs``/``mksquashfs`` anywhere in
    this repository or its CI dependencies - the SAME real,
    already-established constraint
    ``extract-snap-change-forensics.sh``'s own header and multiple
    ``docs/installer/known-limitations.md`` entries, going back to
    S7.1R7/R12, already document) to bake such a unit into the live
    squashfs at BUILD time. Using `systemd.run=` itself to write that
    unit file at BOOT time would reintroduce the exact real, proven
    defect this round exists to fix - a genuine chicken-and-egg
    constraint given the current toolchain. Rather than invent an
    early-boot injection mechanism this development environment has no
    way to validate (no real QEMU/live-ISO boot here), this round takes
    the conservative, ALREADY-PROVEN-SAFE path: early-commands is
    Subiquity's own normal execution point, so it structurally CANNOT
    disrupt the live session's own boot graph the way `systemd.run=`
    real evidence proved it can - Subiquity's own normal install flow is
    what invokes it, never a kernel-level generator that substitutes for
    part of that flow.

    **The honest tradeoff**: the watcher now starts LATER (once
    Subiquity reaches early-commands, itself gated on snapd.seeded
    having already completed) than R16-R18's ~280s aspirational ideal -
    real-time observation of snapd's own VERY FIRST startup moment is
    lost this round. But it is still capable of observing whatever
    remains of an in-progress snap/bootstrap pathology (snapd.hold,
    desktop-security-center activity, a still-missing
    ``/snap/snapd/current``, etc.) for as long as any of that continues
    after Subiquity itself becomes runnable - and, critically, a
    working, non-blocking watcher that lets the real installer run is
    strictly more valuable than an earlier one that prevents the
    installer from running at all (real Run #19's own proof). A future
    round may revisit a genuinely early, boot-graph-integrated
    mechanism if real squashfs-modification tooling is ever added to
    this project - not attempted here, matching this round's own
    explicit narrow-corrective scope."""
    encoded = base64.b64encode(
        build_qa_evidence_launcher_script().encode("utf-8")
    ).decode("ascii")
    return f"sh -c 'echo {encoded} | base64 -d | sh >/dev/null 2>&1 &' || true"


def render_autoinstall_yaml(
    plan: InstallPlan,
    qa_credential: QaCredential,
    install_state: InstallStateMarker,
    *,
    qa_mode: bool,
) -> str:
    """Render a full ``autoinstall.yaml`` document for ``plan``.

    ``qa_mode`` must be passed explicitly as ``True`` - this is a
    deliberate code-level tripwire (Section 6-7): production Serein
    media must never carry ``autoinstall``, and this function refusing
    to run without an explicit, visible ``qa_mode=True`` at every call
    site makes an accidental production wiring impossible to introduce
    silently. Never accepts a caller-supplied identity/storage
    dict - only ever renders from an already-validated
    :class:`~serein.installer.models.InstallPlan` (Section 25).
    """
    if not qa_mode:
        raise RendererError(
            "render_autoinstall_yaml refuses to run outside qa_mode=True - "
            "production media must never carry autoinstall (Section 6)"
        )
    _require_valid_plan(plan)

    storage = render_autoinstall_storage_config(plan)

    document = {
        "autoinstall": {
            "version": 1,
            "identity": {
                "hostname": "serein-qa",
                "username": qa_credential.username,
                "password": qa_credential.password_hash,
            },
            "ssh": {"install-server": False, "allow-pw": False},
            "storage": storage,
            # S7.1R16-R18 tried starting the QA guest-evidence watcher
            # independently of Subiquity, via a `systemd.run=` kernel
            # command-line token - real Run #19 evidence
            # (RUN_ID=34832918752) proved that token's mere presence
            # prevents the rest of the normal live-session boot graph
            # (snapd, Subiquity, everything) from ever starting, even
            # though the launcher it triggers completes correctly. S7.1R19
            # returns the launch trigger to Subiquity's own
            # early-commands directive - the ORIGINAL S7.1R14 mechanism,
            # already proven not to disrupt the live session's own boot
            # graph, since it is Subiquity's own normal execution point -
            # see _qa_evidence_launcher_early_command's own docstring for
            # the full history, the real tooling constraint that ruled
            # out a persisted boot-graph-integrated unit, and the honest
            # timing tradeoff this reversion accepts.
            "early-commands": [_qa_evidence_launcher_early_command()],
            "late-commands": [_install_state_late_command(install_state)],
        }
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"
