"""Structured representation of a Serein profile manifest.

Mirrors ``schemas/profile.schema.json``. A profile is a declarative
description of a Serein capability bundle — S0 defines the shape only;
most fields (packages, services, verification_checks, ...) are contract
surface for later phases and are empty/inert today. See
``docs/architecture/profile-contract.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 1

ProfileStatus = Literal["declared", "implemented"]


@dataclass
class RollbackInfo:
    supported: bool = False
    notes: str | None = None


@dataclass
class ProfileManifest:
    schema_version: int
    id: str
    name: str
    version: str
    status: ProfileStatus
    description: str
    dependencies: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    configuration_units: list[str] = field(default_factory=list)
    hardware_conditions: list[str] = field(default_factory=list)
    verification_checks: list[str] = field(default_factory=list)
    rollback: RollbackInfo = field(default_factory=RollbackInfo)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ProfileManifest:
        rollback_data = data.get("rollback") or {}
        return ProfileManifest(
            schema_version=data["schema_version"],
            id=data["id"],
            name=data["name"],
            version=data["version"],
            status=data["status"],
            description=data["description"],
            dependencies=list(data.get("dependencies", [])),
            conflicts=list(data.get("conflicts", [])),
            packages=list(data.get("packages", [])),
            services=list(data.get("services", [])),
            configuration_units=list(data.get("configuration_units", [])),
            hardware_conditions=list(data.get("hardware_conditions", [])),
            verification_checks=list(data.get("verification_checks", [])),
            rollback=RollbackInfo(
                supported=bool(rollback_data.get("supported", False)),
                notes=rollback_data.get("notes"),
            ),
        )


@dataclass
class ProfileEntry:
    """One row of ``serein profile list``: a manifest-backed profile or a
    declared-only stub, plus S0's (always-inactive) activation state."""

    id: str
    name: str
    description: str
    status: ProfileStatus
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
