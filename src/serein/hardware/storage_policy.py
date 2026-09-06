"""Block-device I/O scheduler detection via ``/sys/block/<dev>/queue/scheduler``.

The kernel exposes the active scheduler in brackets among the available
ones on a single line, e.g. ``"mq-deadline [none] bfq"``. This module only
reads that file — it never writes a scheduler. Uses the same exclusion
list as ``serein.hardware.storage`` (loopback/ram/optical/device-mapper/
software-raid/zram are not physical storage), duplicated rather than
imported to keep each probe module independently simple, matching the
rest of this package's style.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import StoragePolicyInfo, StorageSchedulerInfo

_EXCLUDED_PREFIXES = ("loop", "ram", "sr", "dm-", "md", "zram")


def _parse_scheduler(text: str) -> tuple[str | None, list[str]]:
    current: str | None = None
    available: list[str] = []
    for token in text.split():
        name = token.strip("[]")
        available.append(name)
        if token.startswith("[") and token.endswith("]"):
            current = name
    return current, available


def detect_storage_policy(root: Path) -> StoragePolicyInfo:
    block_dir = root / "sys" / "block"
    if not block_dir.is_dir():
        return StoragePolicyInfo()

    try:
        names = sorted(p.name for p in block_dir.iterdir())
    except OSError:
        return StoragePolicyInfo()

    devices: list[StorageSchedulerInfo] = []
    for name in names:
        if name.startswith(_EXCLUDED_PREFIXES):
            continue
        scheduler_text = read_text(block_dir / name / "queue" / "scheduler")
        current, available = _parse_scheduler(scheduler_text) if scheduler_text else (None, [])
        devices.append(
            StorageSchedulerInfo(
                name=name, current_scheduler=current, available_schedulers=available
            )
        )

    return StoragePolicyInfo(devices=devices)
