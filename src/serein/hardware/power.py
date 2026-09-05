"""Power source detection via ``/sys/class/power_supply``.

Absence of the directory (common on desktops, containers, and non-Linux
hosts) means "no battery", not an error. ``on_ac_power`` stays ``None``
(unknown) rather than ``False`` when it cannot be determined, since a
desktop with no battery is not meaningfully "off AC power".
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import PowerInfo


def detect_power(root: Path) -> PowerInfo:
    supply_dir = root / "sys" / "class" / "power_supply"
    if not supply_dir.is_dir():
        return PowerInfo()

    try:
        entries = sorted(p.name for p in supply_dir.iterdir())
    except OSError:
        return PowerInfo()

    battery_count = 0
    on_ac: bool | None = None

    for name in entries:
        supply_type = read_text(supply_dir / name / "type")
        supply_type = supply_type.strip() if supply_type else ""

        if supply_type == "Battery":
            battery_count += 1
        elif supply_type == "Mains":
            online = read_text(supply_dir / name / "online")
            if online is not None:
                on_ac = online.strip() == "1"

    return PowerInfo(
        has_battery=battery_count > 0,
        battery_count=battery_count,
        on_ac_power=on_ac,
    )
