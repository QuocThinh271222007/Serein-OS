"""Structured representations for the Recovery subsystem (Section
37-41). Mirrors the pattern S1-S7.2 established - dataclasses only,
no behavior."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

#: Section 39: managed-file classification vocabulary.
FILE_STATUSES: tuple[str, ...] = ("OK", "MISSING", "MODIFIED", "CORRUPT", "UNKNOWN")


@dataclass(frozen=True)
class ManagedFileCheck:
    id: str
    target_path: str
    status: str  # one of FILE_STATUSES
    detail: str
    #: True only if `serein.recovery.repair` actually knows how to fix
    #: this exact file - never claims repairability it cannot deliver.
    regeneratable: bool

    def __post_init__(self) -> None:
        if self.status not in FILE_STATUSES:
            raise ValueError(f"status={self.status!r} must be one of {FILE_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryStatusReport:
    schema_version: int
    checks: list[ManagedFileCheck] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.status == "OK" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "healthy": self.healthy,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass(frozen=True)
class RepairAction:
    id: str
    target_path: str
    would_write: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryPlan:
    schema_version: int
    actions: list[RepairAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass(frozen=True)
class RepairResult:
    id: str
    target_path: str
    repaired: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairReport:
    schema_version: int
    results: list[RepairResult] = field(default_factory=list)

    @property
    def all_repaired(self) -> bool:
        return all(r.repaired for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "all_repaired": self.all_repaired,
            "results": [r.to_dict() for r in self.results],
        }
