"""``serein recovery plan`` - side-effect-free preview of what
``repair`` would do. Never itself repairs anything."""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT

from .checks import check_managed_files
from .models import SCHEMA_VERSION, RecoveryPlan, RepairAction


def build_recovery_plan(root: Path = DEFAULT_ROOT) -> RecoveryPlan:
    actions = []
    for check in check_managed_files(root):
        if check.status == "OK":
            continue
        if check.regeneratable:
            actions.append(
                RepairAction(
                    check.id, check.target_path, True,
                    f"would regenerate from serein.branding.os_identity ({check.status})",
                )
            )
        else:
            actions.append(
                RepairAction(
                    check.id, check.target_path, False,
                    f"not repairable automatically ({check.status}: {check.detail})",
                )
            )
    return RecoveryPlan(schema_version=SCHEMA_VERSION, actions=actions)
