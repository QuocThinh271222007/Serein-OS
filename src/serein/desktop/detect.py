"""Read-only desktop detection.

Follows the same injectable-``root`` pattern as ``serein.hardware`` (see
``docs/architecture/hardware-contract.md``), extended with an injectable
``env`` mapping for session detection. Nothing here launches a process,
requires a display, or requires root.

Three distinct questions, kept separate per
``docs/desktop/architecture.md``:

1. Is a component *installed*? (``detect_availability``)
2. Is a graphical session *currently active*, and which kind?
   (``detect_session``)
3. Did Serein *apply* its desktop configuration to this host?
   (``detect_config_state``)
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from serein.desktop.models import ConfigState, DesktopAvailability, SessionInfo
from serein.hardware._util import read_int

_BIN_DIRS = ("usr/bin", "usr/sbin", "bin", "sbin", "usr/local/bin")
_CONFIG_MARKER_REL = "etc/serein/desktop/config-version"


def _binary_present(root: Path, name: str) -> bool:
    return any((root / d / name).is_file() for d in _BIN_DIRS)


def detect_availability(root: Path) -> DesktopAvailability:
    return DesktopAvailability(
        plasma_installed=_binary_present(root, "plasmashell"),
        kwin_wayland_installed=_binary_present(root, "kwin_wayland"),
        kwin_x11_installed=_binary_present(root, "kwin_x11"),
        sddm_installed=_binary_present(root, "sddm"),
    )


def detect_session(env: Mapping[str, str]) -> SessionInfo:
    session_type_raw = (env.get("XDG_SESSION_TYPE") or "").strip().lower()
    session_type = session_type_raw if session_type_raw in ("wayland", "x11") else None

    current_desktop = env.get("XDG_CURRENT_DESKTOP") or env.get("XDG_SESSION_DESKTOP") or ""
    desktop_environment = "KDE" if "kde" in current_desktop.lower() else None

    return SessionInfo(desktop_environment=desktop_environment, session_type=session_type)


def detect_config_state(root: Path) -> ConfigState:
    version = read_int(root / _CONFIG_MARKER_REL)
    return ConfigState(
        serein_preset_applied=version is not None,
        desktop_config_version=version,
    )
