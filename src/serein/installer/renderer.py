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
QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES = 65536
QA_EVIDENCE_WATCHER_MAX_ITERATIONS = 660
QA_EVIDENCE_WATCHER_SLEEP_SECONDS = 10
QA_EVIDENCE_PORT_PATH = "/dev/virtio-ports/org.serein.qa.evidence"


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
    """The guest-side bounded crash-evidence producer (S7.1R14
    Objective A). A POSIX ``/bin/sh`` script (no bashisms - the live
    ISO's default shell is dash) that watches for new
    ``/var/crash/*block_probe_fail*.crash`` files and exports bounded
    metadata + truncated content through the QA-only, structurally
    one-way virtio-serial port ``run-qa-install.sh`` wires up
    (``QA_EVIDENCE_PORT_PATH``).

    Guest-side contract (Section 6's absolute requirements, all held by
    construction here, never by convention):

    - reads ONLY ``/var/crash/*block_probe_fail*.crash`` inside the
      guest's own ephemeral filesystem - never any other host or guest
      path;
    - writes ONLY to the named virtio-serial port - never any other
      file, device, or network socket;
    - never executes a host command, never opens a network connection,
      never accepts input FROM the port (the port is opened purely for
      appending);
    - finite and self-terminating: a fixed ``MAX_ITERATIONS``-step
      loop, never ``while true`` - it exits on its own well before the
      host's own QEMU timeout, rather than depending on the guest ever
      shutting down gracefully;
    - bounded: at most ``MAX_CRASH_FILES`` distinct crash files ever
      exported, at most ``MAX_BYTES_PER_CRASH`` bytes read from any one
      of them, and a hard ``MAX_TOTAL_EVIDENCE_BYTES`` ceiling across
      all of them combined - every truncation is recorded explicitly
      (``truncated=true``/``false``), never silent;
    - deduplicated: an in-memory ``seen`` list keyed by filename, so
      the same crash file is exported at most once per run, even
      though the watcher polls repeatedly.
    """
    return (
        "#!/bin/sh\n"
        "set -u\n"
        f'PORT="{QA_EVIDENCE_PORT_PATH}"\n'
        f"MAX_CRASH_FILES={QA_EVIDENCE_MAX_CRASH_FILES}\n"
        f"MAX_BYTES_PER_CRASH={QA_EVIDENCE_MAX_BYTES_PER_CRASH}\n"
        f"MAX_TOTAL_EVIDENCE_BYTES={QA_EVIDENCE_MAX_TOTAL_EVIDENCE_BYTES}\n"
        f"MAX_ITERATIONS={QA_EVIDENCE_WATCHER_MAX_ITERATIONS}\n"
        f"SLEEP_SECONDS={QA_EVIDENCE_WATCHER_SLEEP_SECONDS}\n"
        'seen=""\n'
        "exported_count=0\n"
        "total_bytes=0\n"
        "i=0\n"
        'while [ "$i" -lt "$MAX_ITERATIONS" ]; do\n'
        '    if [ -e "$PORT" ] && [ -w "$PORT" ]; then\n'
        "        for f in /var/crash/*block_probe_fail*.crash; do\n"
        '            [ -e "$f" ] || continue\n'
        '            case " $seen " in\n'
        '                *" $f "*) continue ;;\n'
        "            esac\n"
        '            seen="$seen $f"\n'
        '            [ "$exported_count" -ge "$MAX_CRASH_FILES" ] && continue\n'
        "            exported_count=$((exported_count + 1))\n"
        '            size=$(wc -c < "$f" 2>/dev/null || echo 0)\n'
        '            mtime=$(stat -c %Y "$f" 2>/dev/null || echo "")\n'
        "            sha256=$(sha256sum \"$f\" 2>/dev/null | cut -d' ' -f1)\n"
        '            take="$MAX_BYTES_PER_CRASH"\n'
        '            remaining=$((MAX_TOTAL_EVIDENCE_BYTES - total_bytes))\n'
        '            [ "$remaining" -lt "$take" ] && take="$remaining"\n'
        '            [ "$take" -le 0 ] && continue\n'
        '            trunc="false"\n'
        '            [ "$size" -gt "$take" ] && trunc="true"\n'
        "            {\n"
        '                echo "===BEGIN-CRASH-EVIDENCE==="\n'
        '                echo "filename=$(basename "$f")"\n'
        '                echo "size=$size"\n'
        '                echo "mtime=$mtime"\n'
        '                echo "sha256=$sha256"\n'
        '                echo "truncated=$trunc"\n'
        '                echo "---BEGIN-CONTENT---"\n'
        '                head -c "$take" "$f" 2>/dev/null\n'
        '                echo ""\n'
        '                echo "---END-CONTENT---"\n'
        '                echo "===END-CRASH-EVIDENCE==="\n'
        '            } >> "$PORT" 2>/dev/null || true\n'
        "            total_bytes=$((total_bytes + take))\n"
        "        done\n"
        "    fi\n"
        "    i=$((i + 1))\n"
        '    sleep "$SLEEP_SECONDS"\n'
        "done\n"
        "exit 0\n"
    )


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
