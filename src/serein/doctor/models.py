"""Result model for ``serein doctor``. Mirrors
``schemas/doctor-report.schema.json``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    id: str
    title: str
    status: CheckStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class DoctorReport:
    schema_version: int
    checks: list[CheckResult]

    @property
    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in CheckStatus}
        for check in self.checks:
            counts[check.status.value] += 1
        return counts

    @property
    def exit_code(self) -> int:
        """0 if no check FAILed, 1 otherwise. WARN/SKIP never affect the
        exit code — WARN is informational and SKIP means "not applicable
        here", neither is a foundation-level failure."""
        return 1 if any(c.status is CheckStatus.FAIL for c in self.checks) else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
        }
