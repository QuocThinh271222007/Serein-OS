"""Serein Desktop's declarative package manifest — the single source of
truth for what a Serein Desktop install requests.

See ``docs/desktop/package-strategy.md`` for the reasoning behind each
group and what was deliberately excluded (``kubuntu-desktop`` as a whole,
``plasma-session-x11``, and everything from S2 onward). This module is
plain data: nothing here executes a package manager.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PackageGroup:
    name: str
    description: str
    packages: tuple[str, ...]


PACKAGE_GROUPS: tuple[PackageGroup, ...] = (
    PackageGroup(
        name="session",
        description="The Plasma shell itself and its Wayland compositor.",
        packages=("plasma-desktop", "plasma-workspace", "kwin-wayland", "systemsettings"),
    ),
    PackageGroup(
        name="login-manager",
        description="Upstream login manager with its upstream theme.",
        packages=("sddm", "sddm-theme-breeze"),
    ),
    PackageGroup(
        name="applications",
        description="Baseline desktop applications needed before S3 adds dev tooling.",
        packages=("dolphin", "konsole", "ark"),
    ),
    PackageGroup(
        name="integration",
        description=(
            "Desktop portals and panel applets — without these the panel looks "
            "complete but basic actions (Wi-Fi, volume, printing) don't work."
        ),
        packages=(
            "xdg-desktop-portal-kde",
            "plasma-nm",
            "plasma-pa",
            "print-manager",
            "kinfocenter",
        ),
    ),
    PackageGroup(
        name="appearance",
        description="Upstream Breeze (and its GTK counterpart) plus Qt/GTK integration.",
        packages=("breeze", "breeze-gtk-theme", "plasma-integration"),
    ),
)


def all_packages() -> list[str]:
    """Every package across all groups, deduplicated and sorted.

    This is the flattened list ``profiles/desktop/desktop.profile.json``
    and ``serein desktop plan`` both use — kept in sync by
    ``tests/test_desktop.py``, so the manifest can never silently drift
    from this module.
    """
    seen: set[str] = set()
    result: list[str] = []
    for group in PACKAGE_GROUPS:
        for pkg in group.packages:
            if pkg not in seen:
                seen.add(pkg)
                result.append(pkg)
    return sorted(result)
