"""Power-management mechanism detection: power-profiles-daemon presence and
per-battery charge state.

``power-profiles-daemon`` exposes no sysfs readback of its active
profile — only D-Bus does. Serein does not execute commands or talk to
D-Bus anywhere in S2 (matching the read-only-filesystem-only detection
style used throughout this project), so presence is detected via stable
on-disk markers (the systemd unit file or the ``powerprofilesctl`` CLI)
rather than by querying the daemon; the *active* profile is therefore
unknown to the planner, never fabricated. See docs/hardware/power-policy.md.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_int, read_text
from serein.hardware.models import BatteryStatus, PowerPolicyInfo

_PPD_MARKERS = (
    ("usr", "bin", "powerprofilesctl"),
    ("usr", "lib", "systemd", "system", "power-profiles-daemon.service"),
    ("lib", "systemd", "system", "power-profiles-daemon.service"),
)


def _ppd_present(root: Path) -> bool:
    return any(root.joinpath(*parts).exists() for parts in _PPD_MARKERS)


def detect_power_policy(root: Path) -> PowerPolicyInfo:
    supply_dir = root / "sys" / "class" / "power_supply"
    batteries: list[BatteryStatus] = []

    if supply_dir.is_dir():
        try:
            names = sorted(p.name for p in supply_dir.iterdir())
        except OSError:
            names = []
        for name in names:
            supply_type = read_text(supply_dir / name / "type")
            if not supply_type or supply_type.strip() != "Battery":
                continue
            capacity = read_int(supply_dir / name / "capacity")
            status = read_text(supply_dir / name / "status")
            batteries.append(
                BatteryStatus(
                    name=name,
                    capacity_percent=capacity,
                    status=status.strip() if status else None,
                )
            )

    return PowerPolicyInfo(ppd_present=_ppd_present(root), batteries=batteries)
