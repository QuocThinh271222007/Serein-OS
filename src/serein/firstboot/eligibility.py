"""Read-only provisioning-eligibility evaluation (Section 5, 10, 33-37).

``evaluate_eligibility`` is the single canonical gate every entrypoint
(``status``, ``doctor``, ``plan``, and the real ``run_firstboot`` engine)
calls before touching anything else - it never mutates, so calling it
from a read-only command is always safe, and the mutating engine reuses
the exact same verdict rather than re-deriving eligibility with
slightly different logic.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT

from .installstate import read_install_state
from .livemedia import detect_live_media
from .models import EligibilityResult


def evaluate_eligibility(root: Path = DEFAULT_ROOT) -> EligibilityResult:
    live_media = detect_live_media(root)
    install_state = read_install_state(root)

    # Section 10: live-media detection is checked first and independently
    # of the handoff marker - LIVE_MEDIA_PROVISIONING=false must hold even
    # if a stray/leftover install-state.json happens to exist on media.
    if live_media.is_live_media:
        return EligibilityResult(
            status="BLOCKED",
            reason=f"live_media_detected: {'; '.join(live_media.reasons) or 'unspecified'}",
            install_state=install_state,
            live_media=live_media,
        )

    if not install_state.present:
        return EligibilityResult(
            status="BLOCKED",
            reason="install_state_missing",
            install_state=install_state,
            live_media=live_media,
        )

    if not install_state.valid:
        return EligibilityResult(
            status="BLOCKED",
            reason=f"install_state_malformed: {install_state.error}",
            install_state=install_state,
            live_media=live_media,
        )

    marker = install_state.marker
    assert marker is not None  # valid=True guarantees this (Section 5)

    if not marker.installation_complete:
        return EligibilityResult(
            status="BLOCKED",
            reason="installation_not_complete",
            install_state=install_state,
            live_media=live_media,
        )

    if marker.firstboot_provisioning == "complete":
        return EligibilityResult(
            status="NOT_REQUIRED",
            reason="firstboot_already_complete",
            install_state=install_state,
            live_media=live_media,
        )

    if marker.firstboot_provisioning != "pending":
        # "unknown" or any future value - fail closed rather than guess.
        return EligibilityResult(
            status="BLOCKED",
            reason=f"firstboot_provisioning_unexpected: {marker.firstboot_provisioning!r}",
            install_state=install_state,
            live_media=live_media,
        )

    return EligibilityResult(
        status="ELIGIBLE",
        reason="install_state_valid_and_pending",
        install_state=install_state,
        live_media=live_media,
    )
