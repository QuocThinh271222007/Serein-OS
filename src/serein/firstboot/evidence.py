"""Assembles and persists machine-readable provisioning evidence
(Section 31)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from serein.installer.payload import InstallStateMarker

from .atomic import atomic_write_json
from .models import (
    FIRSTBOOT_EVIDENCE_SCHEMA_VERSION,
    EligibilityResult,
    FirstbootEvidence,
    FirstbootState,
)


def assemble_firstboot_evidence(
    marker: InstallStateMarker,
    state: FirstbootState,
    step_evidence: dict[str, dict[str, Any]],
    eligibility: EligibilityResult,
) -> FirstbootEvidence:
    return FirstbootEvidence(
        schema_version=FIRSTBOOT_EVIDENCE_SCHEMA_VERSION,
        source_commit=marker.source_commit,
        install_state_valid=eligibility.install_state.valid,
        started_at=state.started_at,
        completed_at=state.completed_at,
        steps=tuple(s.to_dict() for s in state.steps),
        first_failure_stage=state.first_failure_stage,
        first_failure_reason=state.first_failure_reason,
        desktop_baseline=step_evidence.get("04-desktop-baseline", {}).get("desktop_baseline"),
        hardware_snapshot=step_evidence.get("03-apply-core-config", {}).get("hardware_snapshot"),
        forge_registration=step_evidence.get("05-development-registration", {}).get(
            "forge_registration"
        ),
        aether_registration=step_evidence.get("06-ai-registration", {}).get("aether_registration"),
        ward_registration=step_evidence.get("07-cyber-registration", {}).get("ward_registration"),
        veil_registration=step_evidence.get("08-privacy-registration", {}).get("veil_registration"),
        focus_default=step_evidence.get("03-apply-core-config", {}).get("focus_default"),
        # Section 23: OFFLINE_FIRSTBOOT_CORE=SUPPORTED - core provisioning
        # never depends on network reachability, so it is never even
        # probed here; `None` honestly means "not probed", never a
        # fabricated True/False.
        network_required=False,
        network_available=None,
        final_status=state.state,
    )


def write_firstboot_evidence(evidence: FirstbootEvidence, path: Path) -> Path:
    atomic_write_json(path, evidence.to_dict())
    return path


def load_firstboot_evidence(path: Path) -> dict[str, Any] | None:
    """Read-only convenience loader (used by ``doctor``/tests) - returns
    ``None`` rather than raising if no evidence has been written yet."""
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))
