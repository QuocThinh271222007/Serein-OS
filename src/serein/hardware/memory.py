"""Memory sizing via ``/proc/meminfo``.

``MemTotal``/``MemAvailable`` are reported in kibibytes by the kernel; we
normalize to bytes. No fallback exists for non-Linux hosts — a zero-runtime-
dependency, Windows-specific memory probe is out of scope for a Linux-only
target, so those fields simply report unavailable.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import MemoryInfo

_KIB = 1024


def _parse_meminfo(text: str) -> MemoryInfo:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        rest = rest.strip().removesuffix("kB").strip()
        try:
            values[key.strip()] = int(rest)
        except ValueError:
            continue

    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    return MemoryInfo(
        total_bytes=total * _KIB if total is not None else None,
        available_bytes=available * _KIB if available is not None else None,
    )


def read_memory_info(root: Path) -> MemoryInfo:
    text = read_text(root / "proc" / "meminfo")
    if text is None:
        return MemoryInfo()
    return _parse_meminfo(text)
