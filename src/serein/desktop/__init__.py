"""Serein Desktop: KDE Plasma workstation integration (S1).

Configures upstream KDE Plasma rather than replacing any of it — see
``docs/desktop/architecture.md`` and
``docs/architecture/principles.md`` (Integrate -> Measure -> Replace).
"""

from serein.desktop.models import (
    DESKTOP_CONFIG_VERSION,
    SCHEMA_VERSION,
    DesktopPlan,
    DesktopStatusReport,
)
from serein.desktop.plan import build_desktop_plan
from serein.desktop.status import build_desktop_status

__all__ = [
    "DESKTOP_CONFIG_VERSION",
    "SCHEMA_VERSION",
    "DesktopPlan",
    "DesktopStatusReport",
    "build_desktop_plan",
    "build_desktop_status",
]
