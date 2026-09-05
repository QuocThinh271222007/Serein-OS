"""Top-level hardware probe: aggregates every sub-probe into one report.

Each sub-probe already degrades gracefully (missing files -> empty/None
fields, never an exception). This function adds one more safety net: if a
sub-probe still raises for an unanticipated reason, that single section
degrades to its empty default instead of taking down the whole report. A
traceback from ``serein hardware probe`` is always a bug.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.cpu import read_cpu_info
from serein.hardware.environment import detect_environment
from serein.hardware.gpu import detect_gpus
from serein.hardware.kernel import read_kernel_info
from serein.hardware.memory import read_memory_info
from serein.hardware.models import (
    SCHEMA_VERSION,
    CPUInfo,
    EnvironmentInfo,
    GPUDevice,
    HardwareReport,
    KernelInfo,
    MemoryInfo,
    OSInfo,
    PowerInfo,
    StorageDevice,
)
from serein.hardware.os_release import read_os_release
from serein.hardware.power import detect_power
from serein.hardware.storage import detect_storage


def _safely[T](probe: Callable[[Path], T], root: Path, default: T) -> T:
    try:
        return probe(root)
    except Exception:
        return default


def probe_hardware(root: Path = DEFAULT_ROOT) -> HardwareReport:
    return HardwareReport(
        schema_version=SCHEMA_VERSION,
        os=_safely(read_os_release, root, OSInfo()),
        kernel=_safely(read_kernel_info, root, KernelInfo()),
        cpu=_safely(read_cpu_info, root, CPUInfo()),
        memory=_safely(read_memory_info, root, MemoryInfo()),
        gpu=_safely(detect_gpus, root, list[GPUDevice]()),
        storage=_safely(detect_storage, root, list[StorageDevice]()),
        power=_safely(detect_power, root, PowerInfo()),
        environment=_safely(detect_environment, root, EnvironmentInfo()),
    )
