"""``serein desktop status``: a read-only desktop summary.

Safe to run on Ubuntu without KDE, inside WSL, in CI, inside containers,
and on non-Linux development hosts — every field degrades to an honest
"unavailable"/"declared" rather than raising. See
``docs/architecture/security-model.md``: nothing collected here is a
hostname, username, or other identifier.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from serein.desktop.detect import detect_availability, detect_config_state, detect_session
from serein.desktop.models import SCHEMA_VERSION, DesktopStatusReport
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.os_release import read_os_release
from serein.profiles.registry import list_profiles

_TARGET_UBUNTU_VERSION = "26.04"


def _os_compatibility(root: Path) -> str:
    os_info = read_os_release(root)
    if not os_info.id:
        return "unknown (no /etc/os-release found)"
    if not os_info.is_ubuntu:
        return f"unsupported ({os_info.pretty_name or os_info.id})"
    if os_info.version_id == _TARGET_UBUNTU_VERSION:
        return "supported"
    return f"untested (Ubuntu {os_info.version_id or 'unknown'})"


def build_desktop_status(
    root: Path = DEFAULT_ROOT, env: Mapping[str, str] | None = None
) -> DesktopStatusReport:
    if env is None:
        env = os.environ

    profiles = {p.id: p for p in list_profiles()}
    desktop_profile = profiles.get("desktop")

    return DesktopStatusReport(
        schema_version=SCHEMA_VERSION,
        profile_id="desktop",
        profile_status=desktop_profile.status if desktop_profile else "declared",
        os_compatibility=_os_compatibility(root),
        availability=detect_availability(root),
        session=detect_session(env),
        config=detect_config_state(root),
    )
