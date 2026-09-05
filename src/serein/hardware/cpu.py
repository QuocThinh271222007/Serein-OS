"""CPU identification via ``/proc/cpuinfo``.

Physical core count is derived from the number of distinct
``(physical id, core id)`` pairs across all logical processors, matching
how the kernel itself distinguishes hyperthreaded siblings. When
``physical id``/``core id`` are absent (some virtualized or single-socket
kernels omit them), the physical count falls back to the logical count.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from serein.hardware._util import is_real_root, read_text
from serein.hardware.models import CPUInfo

_VENDOR_LABELS = {
    "GenuineIntel": "Intel",
    "AuthenticAMD": "AMD",
}


def _parse_cpuinfo(text: str) -> CPUInfo:
    blocks = [b for b in text.split("\n\n") if b.strip()]
    logical_cores = 0
    vendor_id: str | None = None
    model_name: str | None = None
    core_pairs: set[tuple[str, str]] = set()
    physical_ids_seen: set[str] = set()

    for block in blocks:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

        if "processor" not in fields:
            continue
        logical_cores += 1

        if vendor_id is None and "vendor_id" in fields:
            vendor_id = fields["vendor_id"]
        if model_name is None and "model name" in fields:
            model_name = fields["model name"]

        physical_id = fields.get("physical id")
        core_id = fields.get("core id")
        if physical_id is not None and core_id is not None:
            core_pairs.add((physical_id, core_id))
            physical_ids_seen.add(physical_id)

    physical_cores = len(core_pairs) if core_pairs else (logical_cores or None)

    return CPUInfo(
        vendor=_VENDOR_LABELS.get(vendor_id or "", vendor_id),
        model_name=model_name,
        architecture=platform.machine() or None,
        logical_cores=logical_cores or None,
        physical_cores=physical_cores,
    )


def read_cpu_info(root: Path) -> CPUInfo:
    text = read_text(root / "proc" / "cpuinfo")
    if text is None:
        if is_real_root(root):
            return CPUInfo(
                architecture=platform.machine() or None,
                model_name=platform.processor() or None,
                logical_cores=os.cpu_count(),
            )
        return CPUInfo()
    return _parse_cpuinfo(text)
