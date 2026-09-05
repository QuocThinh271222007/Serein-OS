"""``serein status``: a read-only workstation summary.

Deliberately excludes anything that would make output unsafe to paste into
a bug report: hostname, MAC/IP addresses, disk/machine serial numbers, and
usernames are never collected by the hardware probe in the first place, so
there is nothing to redact here — see ``docs/architecture/security-model.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from serein import __version__
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.models import HardwareReport
from serein.hardware.probe import probe_hardware

_TARGET_UBUNTU_VERSION = "26.04"


def _os_compatibility(report: HardwareReport) -> str:
    os_info = report.os
    if not os_info.id:
        return "unknown (no /etc/os-release found)"
    if not os_info.is_ubuntu:
        return f"unsupported ({os_info.pretty_name or os_info.id})"
    if os_info.version_id == _TARGET_UBUNTU_VERSION:
        return f"supported (Ubuntu {os_info.version_id} LTS)"
    return f"ubuntu, untested version ({os_info.version_id or 'unknown'})"


def _gpu_summary(report: HardwareReport) -> list[str]:
    if not report.gpu:
        return ["unavailable"]
    return [
        f"{gpu.vendor or 'unknown vendor'} ({gpu.kind or 'unknown kind'})" for gpu in report.gpu
    ]


@dataclass
class StatusReport:
    version: str
    os_compatibility: str
    kernel_release: str | None
    architecture: str | None
    cpu_vendor: str | None
    cpu_model: str | None
    logical_cpus: int | None
    memory_total_bytes: int | None
    gpu_summary: list[str]
    virtualization: str
    current_profile: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_status_report(root: Path = DEFAULT_ROOT) -> StatusReport:
    report = probe_hardware(root)
    return StatusReport(
        version=__version__,
        os_compatibility=_os_compatibility(report),
        kernel_release=report.kernel.release,
        architecture=report.cpu.architecture,
        cpu_vendor=report.cpu.vendor,
        cpu_model=report.cpu.model_name,
        logical_cpus=report.cpu.logical_cores,
        memory_total_bytes=report.memory.total_bytes,
        gpu_summary=_gpu_summary(report),
        virtualization=report.environment.virtualization,
        current_profile="none (profile activation is not implemented in S0)",
    )
