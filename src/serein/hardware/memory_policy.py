"""Swap and ZRAM detection.

Never modifies swap or ZRAM state — read-only, mirroring every other S2
detector. ``/proc/swaps`` lists every active swap backend (disk-backed or
ZRAM) uniformly; a device is classified as ``"zram"`` by name rather than
by trusting its reported ``Type`` column, since the kernel reports ZRAM
swap as a plain ``partition`` like any other block-device swap. See
``docs/hardware/memory-policy.md`` for the sizing policy this feeds.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_int, read_text
from serein.hardware.models import MemoryPolicyInfo, SwapDevice, ZramDevice

_ZRAM_GENERATOR_PATHS = (
    ("etc", "systemd", "zram-generator.conf"),
    ("etc", "systemd", "zram-generator.conf.d"),
)


def _parse_swaps(text: str) -> list[SwapDevice]:
    lines = text.splitlines()
    devices: list[SwapDevice] = []
    for line in lines[1:]:  # first line is the column header
        parts = line.split()
        if len(parts) < 5:
            continue
        filename, swap_type, size_kib, _used_kib, priority = parts[:5]
        kind = "zram" if "zram" in filename else swap_type
        try:
            size_bytes: int | None = int(size_kib) * 1024
        except ValueError:
            size_bytes = None
        try:
            prio: int | None = int(priority)
        except ValueError:
            prio = None
        devices.append(SwapDevice(name=filename, kind=kind, size_bytes=size_bytes, priority=prio))
    return devices


def _active_algorithm(comp_algorithm_text: str) -> str | None:
    for token in comp_algorithm_text.split():
        if token.startswith("[") and token.endswith("]"):
            return token[1:-1]
    return None


def _detect_zram_devices(root: Path) -> list[ZramDevice]:
    block_dir = root / "sys" / "block"
    if not block_dir.is_dir():
        return []
    try:
        names = sorted(p.name for p in block_dir.iterdir() if p.name.startswith("zram"))
    except OSError:
        return []

    devices: list[ZramDevice] = []
    for name in names:
        disksize = read_int(block_dir / name / "disksize")
        algo_text = read_text(block_dir / name / "comp_algorithm")
        devices.append(
            ZramDevice(
                name=name,
                disksize_bytes=disksize,
                comp_algorithm=_active_algorithm(algo_text) if algo_text else None,
            )
        )
    return devices


def _zram_generator_config_present(root: Path) -> bool:
    return any(root.joinpath(*parts).exists() for parts in _ZRAM_GENERATOR_PATHS)


def detect_memory_policy(root: Path) -> MemoryPolicyInfo:
    swaps_text = read_text(root / "proc" / "swaps")
    swap_devices = _parse_swaps(swaps_text) if swaps_text else []

    return MemoryPolicyInfo(
        swap_devices=swap_devices,
        zram_devices=_detect_zram_devices(root),
        zram_generator_config_present=_zram_generator_config_present(root),
    )
