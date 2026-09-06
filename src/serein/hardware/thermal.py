"""Thermal telemetry detection via ``/sys/class/thermal`` and ``/sys/class/hwmon``.

Read-only, descriptive only. Serein never writes to any thermal or fan
control interface, and this module deliberately exposes only aggregate
presence/values — no per-machine identifying data. See
``docs/hardware/power-policy.md`` (thermal awareness section) for how
this feeds profile planning (informational only, never a threshold
override).
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_int, read_text
from serein.hardware.models import ThermalInfo, ThermalZoneInfo


def detect_thermal(root: Path) -> ThermalInfo:
    zones: list[ThermalZoneInfo] = []
    thermal_dir = root / "sys" / "class" / "thermal"
    if thermal_dir.is_dir():
        try:
            names = sorted(
                p.name for p in thermal_dir.iterdir() if p.name.startswith("thermal_zone")
            )
        except OSError:
            names = []
        for name in names:
            zone_type = read_text(thermal_dir / name / "type")
            temp_milli = read_int(thermal_dir / name / "temp")
            zones.append(
                ThermalZoneInfo(
                    zone_type=zone_type.strip() if zone_type else None,
                    temp_celsius=(temp_milli / 1000) if temp_milli is not None else None,
                )
            )

    hwmon_dir = root / "sys" / "class" / "hwmon"
    hwmon_present = False
    if hwmon_dir.is_dir():
        try:
            hwmon_present = any(hwmon_dir.iterdir())
        except OSError:
            hwmon_present = False

    return ThermalInfo(zones=zones, hwmon_present=hwmon_present)
