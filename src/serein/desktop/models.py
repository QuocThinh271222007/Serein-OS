"""Structured representations for the desktop subsystem.

``DesktopStatusReport`` mirrors ``schemas/desktop-state.schema.json``;
``DesktopPlan`` mirrors ``schemas/desktop-plan.schema.json``. Keep these in
sync — a field added here without a matching schema/test update is a
contract break, per the same rule S0's hardware module follows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

#: Independent of ``serein.__version__`` (see
#: docs/desktop/configuration-ownership.md) — bump this only when the
#: shape/semantics of what Serein writes under /etc/xdg or
#: /etc/serein/desktop changes in a way a future migration needs to know
#: about.
DESKTOP_CONFIG_VERSION = 1

#: The one Ubuntu release Serein Desktop actively targets. Shared by
#: ``status.py`` (os_compatibility string) and ``doctor.py`` (PASS/WARN
#: semantics) so the two surfaces can never silently disagree about which
#: release is "supported" — see docs/validation/s1r/known-blockers.md.
TARGET_UBUNTU_VERSION = "26.04"


@dataclass
class DesktopAvailability:
    plasma_installed: bool = False
    kwin_wayland_installed: bool = False
    kwin_x11_installed: bool = False
    sddm_installed: bool = False


@dataclass
class SessionInfo:
    desktop_environment: str | None = None  # "KDE" or None
    session_type: str | None = None  # "wayland" | "x11" | None


@dataclass
class ConfigState:
    serein_preset_applied: bool = False
    desktop_config_version: int | None = None


@dataclass
class DesktopStatusReport:
    schema_version: int
    profile_id: str
    profile_status: str  # "declared" | "implemented"
    os_compatibility: str
    availability: DesktopAvailability
    session: SessionInfo
    config: ConfigState

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanStep:
    category: str  # "system" | "user"
    action: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DesktopPlan:
    schema_version: int
    packages: list[str] = field(default_factory=list)
    system_configuration: list[PlanStep] = field(default_factory=list)
    user_configuration: list[PlanStep] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "packages": list(self.packages),
            "system_configuration": [s.to_dict() for s in self.system_configuration],
            "user_configuration": [s.to_dict() for s in self.user_configuration],
            "verification": list(self.verification),
        }
