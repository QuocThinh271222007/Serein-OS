"""``serein firstboot status``: a read-only summary (Section 12).

Never mutates anything - reuses :func:`serein.firstboot.eligibility.evaluate_eligibility`
and :meth:`serein.firstboot.statefile.FirstbootStateStore.load_corrupt_safe`,
both of which are themselves read-only.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT

from .eligibility import evaluate_eligibility
from .models import (
    FIRSTBOOT_STATE_RELATIVE_PATH,
    FIRSTBOOT_STATUS_SCHEMA_VERSION,
    STEP_STATUSES,
    FirstbootStatusReport,
)
from .statefile import FirstbootStateStore


def build_firstboot_status(root: Path = DEFAULT_ROOT) -> FirstbootStatusReport:
    eligibility = evaluate_eligibility(root)
    store = FirstbootStateStore(root / FIRSTBOOT_STATE_RELATIVE_PATH)
    state, corrupt_error = store.load_corrupt_safe()

    if corrupt_error is not None:
        overall_state = "corrupt"
        steps_summary = {status: 0 for status in STEP_STATUSES}
        first_failure_stage: str | None = None
        first_failure_reason: str | None = corrupt_error
    elif state is None:
        overall_state = "not_started"
        steps_summary = {status: 0 for status in STEP_STATUSES}
        first_failure_stage = None
        first_failure_reason = None
    else:
        overall_state = state.state
        steps_summary = {status: 0 for status in STEP_STATUSES}
        for step in state.steps:
            steps_summary[step.status] = steps_summary.get(step.status, 0) + 1
        first_failure_stage = state.first_failure_stage
        first_failure_reason = state.first_failure_reason

    marker = eligibility.install_state.marker
    return FirstbootStatusReport(
        schema_version=FIRSTBOOT_STATUS_SCHEMA_VERSION,
        eligibility_status=eligibility.status,
        eligibility_reason=eligibility.reason,
        install_state_present=eligibility.install_state.present,
        install_state_valid=eligibility.install_state.valid,
        firstboot_provisioning=marker.firstboot_provisioning if marker is not None else None,
        state=overall_state,
        steps_summary=steps_summary,
        first_failure_stage=first_failure_stage,
        first_failure_reason=first_failure_reason,
        live_media_detected=eligibility.live_media.is_live_media,
    )
