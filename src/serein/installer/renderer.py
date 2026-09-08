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
            "late-commands": [_install_state_late_command(install_state)],
        }
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"
