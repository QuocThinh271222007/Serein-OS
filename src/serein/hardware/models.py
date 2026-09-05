"""Structured representation of a hardware report.

This mirrors ``schemas/hardware-report.schema.json``. Keep the two in sync:
a field added here without a matching schema/test update is a contract
break.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class OSInfo:
    id: str | None = None
    id_like: list[str] = field(default_factory=list)
    name: str | None = None
    version_id: str | None = None
    pretty_name: str | None = None
    is_ubuntu: bool = False


@dataclass
class KernelInfo:
    name: str | None = None
    release: str | None = None
    version: str | None = None


@dataclass
class CPUInfo:
    vendor: str | None = None
    model_name: str | None = None
    architecture: str | None = None
    logical_cores: int | None = None
    physical_cores: int | None = None


@dataclass
class MemoryInfo:
    total_bytes: int | None = None
    available_bytes: int | None = None


@dataclass
class GPUDevice:
    vendor: str | None = None
    model: str | None = None
    kind: str | None = None  # "integrated" | "discrete" | "unknown"


@dataclass
class StorageDevice:
    name: str | None = None
    device_class: str | None = None  # "nvme" | "ssd" | "hdd" | "unknown"
    size_bytes: int | None = None


@dataclass
class PowerInfo:
    has_battery: bool = False
    battery_count: int = 0
    on_ac_power: bool | None = None  # None means "unknown", not "false"


@dataclass
class EnvironmentInfo:
    # "none" | "wsl" | "container" | "kvm" | "vmware" | "virtualbox" | "hyperv"
    # | "unknown-hypervisor"
    virtualization: str = "none"
    is_wsl: bool = False
    is_container: bool = False


@dataclass
class HardwareReport:
    schema_version: int
    os: OSInfo
    kernel: KernelInfo
    cpu: CPUInfo
    memory: MemoryInfo
    gpu: list[GPUDevice]
    storage: list[StorageDevice]
    power: PowerInfo
    environment: EnvironmentInfo

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
