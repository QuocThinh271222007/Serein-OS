"""Read-only development-workstation detection, capability modeling, and
planning.

Every detection function accepts an injectable ``runner`` (see
``runner.py``) and, where a filesystem marker matters (e.g. ``~/.nvm``),
an injectable ``home`` path — production code uses the real subprocess
runner and ``Path.home()``; tests inject fakes. See
``docs/development/architecture.md``.
"""

from serein.development.models import (
    DEV_CAPABILITIES_SCHEMA_VERSION,
    DEV_PLAN_SCHEMA_VERSION,
    DevelopmentPlan,
)
from serein.development.planner import build_development_plan

__all__ = [
    "DEV_CAPABILITIES_SCHEMA_VERSION",
    "DEV_PLAN_SCHEMA_VERSION",
    "DevelopmentPlan",
    "build_development_plan",
]
