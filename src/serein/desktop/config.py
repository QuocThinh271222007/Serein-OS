"""Canonical list of the desktop configuration resources this repository
ships under ``desktop/``, and where each would eventually land on a real
host. See ``docs/desktop/configuration-ownership.md`` for the ownership
model these targets rely on (``/etc/xdg`` as a defaults layer beneath
``~/.config``, never a write to any user's home directory).

Nothing in this module writes to the target paths — they are documentation
of intent, consumed by ``desktop.plan`` and ``desktop.doctor`` to describe
and verify what a future Apply step would install.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ConfigResource:
    id: str
    repo_path: str
    target_path: str
    owner: str  # "system" | "first-login-user"
    description: str


RESOURCES: tuple[ConfigResource, ...] = (
    ConfigResource(
        id="xdg-kdeglobals",
        repo_path="desktop/plasma/kdeglobals",
        target_path="/etc/xdg/kdeglobals",
        owner="system",
        description="Serein color scheme, icon theme, and Look-and-Feel default.",
    ),
    ConfigResource(
        id="xdg-kwinrc",
        repo_path="desktop/kwin/kwinrc",
        target_path="/etc/xdg/kwinrc",
        owner="system",
        description="Conservative KWin/virtual-desktop defaults.",
    ),
    ConfigResource(
        id="sddm-dropin",
        repo_path="desktop/sddm/serein.conf",
        target_path="/etc/sddm.conf.d/90-serein.conf",
        owner="system",
        description="SDDM theme pin; autologin left explicitly disabled.",
    ),
    ConfigResource(
        id="color-scheme",
        repo_path="desktop/color-schemes/SereinDark.colors",
        target_path="/usr/share/color-schemes/SereinDark.colors",
        owner="system",
        description="The Serein Dark KDE color scheme.",
    ),
    ConfigResource(
        id="konsole-profile",
        repo_path="desktop/konsole/Serein.profile",
        target_path="/usr/share/konsole/Serein.profile",
        owner="system",
        description="Serein Konsole profile, offered as an available choice.",
    ),
    ConfigResource(
        id="konsole-colorscheme",
        repo_path="desktop/konsole/SereinDark.colorscheme",
        target_path="/usr/share/konsole/SereinDark.colorscheme",
        owner="system",
        description="Konsole-format color scheme matching the desktop accent.",
    ),
    ConfigResource(
        id="lookandfeel-metadata",
        repo_path="desktop/plasma/look-and-feel/org.serein.desktop/metadata.json",
        target_path="/usr/share/plasma/look-and-feel/org.serein.desktop/metadata.json",
        owner="first-login-user",
        description="Look-and-Feel KPackage identity.",
    ),
    ConfigResource(
        id="lookandfeel-layout",
        repo_path=(
            "desktop/plasma/look-and-feel/org.serein.desktop/"
            "contents/layouts/org.kde.plasma.desktop-layout.js"
        ),
        target_path=(
            "/usr/share/plasma/look-and-feel/org.serein.desktop/"
            "contents/layouts/org.kde.plasma.desktop-layout.js"
        ),
        owner="first-login-user",
        description="Default bottom-panel layout applied only at first login.",
    ),
)


def repo_root() -> Path:
    return _REPO_ROOT


def missing_resources(root: Path | None = None) -> list[ConfigResource]:
    """Resources declared above whose repo_path file does not actually
    exist. A non-empty result means the repository itself is missing a
    file it claims to ship — a packaging defect, not a host state."""
    base = root if root is not None else _REPO_ROOT
    return [r for r in RESOURCES if not (base / r.repo_path).is_file()]
