"""Reads and validates the S7.1 -> S7.2 handoff contract,
``/etc/serein/install-state.json`` (Section 5).

Deliberately reuses ``serein.installer.payload.InstallStateMarker`` and
``serein.installer.models.INSTALL_STATE_SCHEMA_VERSION``/``INSTALLER_PHASE``
rather than redefining the schema here - S7.1 owns the marker shape
(``schemas/installer-install-state.schema.json``); S7.2 only ever
*consumes* it (Section 5: "Read the ACTUAL current schema from
src/serein/installer/payload.py... it must match reality exactly, not
this illustrative sketch"). This module never writes anything - it is
purely a read-only validator; the one place S7.2 ever writes back to
this file is ``serein.firstboot.steps.step_mark_complete``.
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT, read_text
from serein.installer.models import INSTALL_STATE_SCHEMA_VERSION, INSTALLER_PHASE
from serein.installer.payload import InstallStateMarker

from .models import INSTALL_STATE_RELATIVE_PATH, InstallStateReadResult

_VALID_FIRSTBOOT_VALUES = ("pending", "complete", "unknown")


def install_state_path(root: Path = DEFAULT_ROOT) -> Path:
    return root / INSTALL_STATE_RELATIVE_PATH


def read_install_state(root: Path = DEFAULT_ROOT) -> InstallStateReadResult:
    """Read and structurally validate the handoff marker.

    Never raises - every failure mode (missing file, malformed JSON, a
    field with the wrong type/value) becomes an honest ``valid=False``
    result with a machine-readable ``error`` code, per Section 5's "Do
    not silently provision if the handoff file is absent or malformed."
    """
    path = install_state_path(root)
    text = read_text(path)
    if text is None:
        return InstallStateReadResult(present=False, valid=False, marker=None, error="missing")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return InstallStateReadResult(
            present=True, valid=False, marker=None, error=f"malformed_json: {exc}"
        )

    if not isinstance(data, dict):
        return InstallStateReadResult(
            present=True, valid=False, marker=None, error="malformed_json: not an object"
        )

    error = _validate_fields(data)
    if error is not None:
        return InstallStateReadResult(present=True, valid=False, marker=None, error=error)

    marker = InstallStateMarker(
        schema_version=data["schema_version"],
        phase=data["phase"],
        installation_complete=data["installation_complete"],
        firstboot_provisioning=data["firstboot_provisioning"],
        source_media_version=data["source_media_version"],
        source_commit=data["source_commit"],
    )
    return InstallStateReadResult(present=True, valid=True, marker=marker, error=None)


def _validate_fields(data: dict) -> str | None:  # type: ignore[type-arg]
    required = (
        "schema_version", "phase", "installation_complete", "firstboot_provisioning",
        "source_media_version", "source_commit",
    )
    for field_name in required:
        if field_name not in data:
            return f"schema_mismatch: missing field {field_name!r}"

    if data["schema_version"] != INSTALL_STATE_SCHEMA_VERSION:
        return (
            f"schema_mismatch: schema_version={data['schema_version']!r}, "
            f"expected {INSTALL_STATE_SCHEMA_VERSION!r}"
        )
    if data["phase"] != INSTALLER_PHASE:
        return f"schema_mismatch: phase={data['phase']!r}, expected {INSTALLER_PHASE!r}"
    if not isinstance(data["installation_complete"], bool):
        return "schema_mismatch: installation_complete must be a boolean"
    if data["firstboot_provisioning"] not in _VALID_FIRSTBOOT_VALUES:
        return (
            f"schema_mismatch: firstboot_provisioning={data['firstboot_provisioning']!r} "
            f"must be one of {_VALID_FIRSTBOOT_VALUES}"
        )
    if not isinstance(data["source_media_version"], str):
        return "schema_mismatch: source_media_version must be a string"
    if not isinstance(data["source_commit"], str):
        return "schema_mismatch: source_commit must be a string"
    return None
