"""``serein recovery doctor`` - reuses the SAME
``serein.doctor.models.DoctorReport``/``CheckResult`` shape every
other subsystem's doctor command already uses (Section 2 - never a
parallel report shape)."""

from __future__ import annotations

from pathlib import Path

from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT

from .checks import check_managed_files

#: Section 39's classification -> this project's shared PASS/WARN/FAIL
#: vocabulary. MISSING/MODIFIED/CORRUPT are real integrity problems on
#: a system that claims to be managed by Serein - FAIL. UNKNOWN is
#: honestly "cannot verify, not itself a proven problem" - WARN, never
#: FAIL (Section 89 - a defect only blocks on a material threat, and
#: an unverifiable-but-present file is not one).
_STATUS_MAP: dict[str, CheckStatus] = {
    "OK": CheckStatus.PASS,
    "MISSING": CheckStatus.FAIL,
    "MODIFIED": CheckStatus.FAIL,
    "CORRUPT": CheckStatus.FAIL,
    "UNKNOWN": CheckStatus.WARN,
}


def run_recovery_checks(root: Path = DEFAULT_ROOT) -> DoctorReport:
    checks = [
        CheckResult(
            id=f"recovery_{c.id.replace('-', '_')}",
            title=f"managed file: {c.target_path}",
            status=_STATUS_MAP[c.status],
            detail=c.detail,
        )
        for c in check_managed_files(root)
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
