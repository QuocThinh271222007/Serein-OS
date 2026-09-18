"""``serein recovery status`` - read-only managed-file health summary."""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT

from .checks import check_managed_files
from .models import SCHEMA_VERSION, RecoveryStatusReport


def build_recovery_status(root: Path = DEFAULT_ROOT) -> RecoveryStatusReport:
    return RecoveryStatusReport(schema_version=SCHEMA_VERSION, checks=check_managed_files(root))
