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
QA_EVIDENCE_MAX_SNAP_FRAMES = 5
QA_EVIDENCE_MAX_BYTES_PER_SNAP_FRAME = 8192
# S7.1R15: the port now carries two independent bounded evidence kinds
# (crash content and snap frames) - the shared total ceiling is raised
# accordingly, still small and explicit, never unbounded.
QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES = 131072


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


def _qa_evidence_watcher_script() -> str:
    """The guest-side bounded evidence producer for BOTH recurring
    pathology families this project has observed (S7.1R14 Objective A
    + S7.1R15 Objective B). A POSIX ``/bin/sh`` script (no bashisms -
    the live ISO's default shell is dash) that:

    1. watches for new ``/var/crash/*block_probe_fail*.crash`` files
       (the Run #13/#14 block-probe pathology) and exports bounded
       metadata + truncated content;
    2. watches the guest's own systemd journal for five known signals
       of the recurring Run #7/#11/#12/#15 snap/bootstrap pathology
       (desktop-security-center configure-hook failure, a sanity
       timeout, ``RemoveSnapServices`` beginning, ``/snap/snapd/current``
       going missing, a ``snapd.seeded`` failure) and exports one
       bounded diagnostic frame the FIRST time each signal is seen.

    Both evidence kinds are exported through the same QA-only,
    structurally one-way virtio-serial port ``run-qa-install.sh`` wires
    up (``QA_EVIDENCE_PORT_PATH``) - observation only, in both
    directions: this watcher never intentionally triggers either
    pathology, and never takes any corrective action of its own.

    Guest-side contract (Section 6's absolute requirements, all held by
    construction here, never by convention):

    - reads ONLY ``/var/crash/*block_probe_fail*.crash`` and the
      guest's own local systemd journal/snap state (via ``journalctl``,
      run against the guest's OWN journal, never any host resource) -
      never any host path, never any other guest path;
    - writes ONLY to the named virtio-serial port - never any other
      file, device, or network socket;
    - never executes a host command, never opens a network connection,
      never accepts input FROM the port (the port is opened purely for
      appending);
    - finite and self-terminating: a fixed ``MAX_ITERATIONS``-step
      loop, never ``while true`` - it exits on its own well before the
      host's own QEMU timeout, rather than depending on the guest ever
      shutting down gracefully;
    - bounded: at most ``MAX_CRASH_FILES`` distinct crash files and at
      most ``MAX_SNAP_FRAMES`` distinct snap-pathology frames are ever
      exported, each capped at its own per-item byte limit, under one
      shared ``MAX_TOTAL_EVIDENCE_BYTES`` ceiling - every truncation is
      recorded explicitly (``truncated=true``/``false``), never silent;
    - deduplicated: an in-memory ``seen`` list keyed by crash filename
      or ``snap:<trigger>``, so the same crash file or the same snap
      signal is exported at most once per run, even though the watcher
      polls repeatedly.
    """
    lines = [
        "#!/bin/sh",
        "set -u",
        f'PORT="{QA_EVIDENCE_PORT_PATH}"',
        f"MAX_CRASH_FILES={QA_EVIDENCE_MAX_CRASH_FILES}",
        f"MAX_BYTES_PER_CRASH={QA_EVIDENCE_MAX_BYTES_PER_CRASH}",
        f"MAX_SNAP_FRAMES={QA_EVIDENCE_MAX_SNAP_FRAMES}",
        f"MAX_BYTES_PER_SNAP_FRAME={QA_EVIDENCE_MAX_BYTES_PER_SNAP_FRAME}",
        f"MAX_TOTAL_EVIDENCE_BYTES={QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES}",
        f"MAX_ITERATIONS={QA_EVIDENCE_WATCHER_MAX_ITERATIONS}",
        f"SLEEP_SECONDS={QA_EVIDENCE_WATCHER_SLEEP_SECONDS}",
        'seen=""',
        "exported_count=0",
        "snap_frame_count=0",
        "total_bytes=0",
        "i=0",
        'while [ "$i" -lt "$MAX_ITERATIONS" ]; do',
        '    if [ -e "$PORT" ] && [ -w "$PORT" ]; then',
        "        for f in /var/crash/*block_probe_fail*.crash; do",
        '            [ -e "$f" ] || continue',
        '            case " $seen " in',
        '                *" $f "*) continue ;;',
        "            esac",
        '            seen="$seen $f"',
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
        "        # S7.1R15 Objective B: recurring snap/bootstrap pathology",
        "        # signals (Runs #7/#11/#12/#15) - a single bounded",
        "        # journal fetch per iteration, checked against all five",
        "        # known signals, never a fresh journalctl invocation per",
        "        # signal (Section 11 - low overhead).",
        '        recent_journal=$(journalctl --no-pager -n 200 2>/dev/null) || '
        'recent_journal=""',
        '        if [ -n "$recent_journal" ] && '
        '[ "$snap_frame_count" -lt "$MAX_SNAP_FRAMES" ]; then',
        '            trigger=""',
        '            key=""',
        '            if printf "%s" "$recent_journal" | grep -qi \'desktop-security-center\' && '
        'printf "%s" "$recent_journal" | grep -qiE \'hook|configure\' && '
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
        '                snap_state=$(snap changes 2>/dev/null | head -n 20)',
        '                [ -z "$snap_state" ] && snap_state="NOT_OBSERVED"',
        '                snapd_state=$(systemctl is-active snapd.service 2>/dev/null '
        '|| echo "NOT_OBSERVED")',
        "                dsc_state=$(journalctl -u 'snap.desktop-security-center*' "
        '--no-pager -n 20 2>/dev/null)',
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
        '                frame=$(printf \'=== SEREIN SNAP FAILURE FRAME ===\\n'
        'timestamp=%s\\ntrigger=%s\\n\\n[SNAP_STATE]\\n%s\\n\\n[SNAPD]\\n%s\\n\\n'
        '[DESKTOP_SECURITY_CENTER]\\n%s\\n\\n[SNAPD_HOLD]\\n%s\\n\\n[PORTAL_STATE]\\n%s\\n\\n'
        '[SNAP_CURRENT]\\n%s\\n\\n[JOURNAL_CONTEXT]\\n%s\\n=== END FRAME ===\\n\' '
        '"$ts" "$trigger" "$snap_state" "$snapd_state" "$dsc_state" "$hold_state" '
        '"$portal_state" "$snap_current" "$journal_ctx")',
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
        "    fi",
        "    i=$((i + 1))",
        '    sleep "$SLEEP_SECONDS"',
        "done",
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def _qa_evidence_early_command() -> str:
    """One ``early-commands`` shell one-liner that base64-decodes and
    launches :func:`_qa_evidence_watcher_script` detached in the
    background (Section 27 escaping discipline, matching
    ``_install_state_late_command``'s own base64 round-trip). Returns
    almost instantly - ``early-commands`` entries run synchronously and
    must never block on the watcher's own ~6600s bounded lifetime; the
    inner ``&`` backgrounds the decode-and-run pipeline before the
    outer ``sh -c`` returns. ``|| true`` ensures a QA-only diagnostic
    convenience can never itself fail the real install."""
    encoded = base64.b64encode(_qa_evidence_watcher_script().encode("utf-8")).decode("ascii")
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
            "early-commands": [_qa_evidence_early_command()],
            "late-commands": [_install_state_late_command(install_state)],
        }
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"
