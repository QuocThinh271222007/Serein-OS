"""Block device classification via ``/sys/block``.

Classification is name/attribute based rather than following the
``device`` symlink to a PCI path, so it works identically on a real host
and on a plain-directory fixture tree (symlinks are awkward to create
portably in test fixtures, notably on Windows).

Virtual and non-disk block devices (loopback, ramdisk, device-mapper,
optical) are excluded — they are not physical storage.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_int
from serein.hardware.models import StorageDevice

_EXCLUDED_PREFIXES = ("loop", "ram", "sr", "dm-", "md", "zram")
_SECTOR_SIZE = 512


def _classify(name: str, rotational: int | None) -> str:
    if name.startswith("nvme"):
        return "nvme"
    if rotational == 0:
        return "ssd"
    if rotational == 1:
        return "hdd"
    return "unknown"


def detect_storage(root: Path) -> list[StorageDevice]:
    block_dir = root / "sys" / "block"
    if not block_dir.is_dir():
        return []

    try:
        entries = sorted(p.name for p in block_dir.iterdir())
    except OSError:
        return []

    devices: list[StorageDevice] = []
    for name in entries:
        if name.startswith(_EXCLUDED_PREFIXES):
            continue
        rotational = read_int(block_dir / name / "queue" / "rotational")
        sectors = read_int(block_dir / name / "size")
        size_bytes = sectors * _SECTOR_SIZE if sectors is not None else None
        devices.append(
            StorageDevice(
                name=name,
                device_class=_classify(name, rotational),
                size_bytes=size_bytes,
            )
        )

    return devices
