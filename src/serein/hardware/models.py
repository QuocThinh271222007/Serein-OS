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


# --- S2: hardware policy model -------------------------------------------
#
# Everything below augments the S0 report above rather than replacing it:
# `serein hardware probe` and HardwareReport/SCHEMA_VERSION are unchanged,
# and every S2 detector below is read-only, taking the same injectable
# ``root`` as the S0 probes. See docs/hardware/architecture.md.

CAPABILITIES_SCHEMA_VERSION = 1
PLAN_SCHEMA_VERSION = 1


@dataclass
class CPUPolicyInfo:
    cpufreq_present: bool = False
    driver: str | None = None  # e.g. "amd-pstate-epp", "intel_pstate", "acpi-cpufreq"
    governor: str | None = None
    available_governors: list[str] = field(default_factory=list)
    epp_current: str | None = None
    epp_available: list[str] = field(default_factory=list)


@dataclass
class SwapDevice:
    name: str | None = None
    kind: str | None = None  # "zram" | "partition" | "file"
    size_bytes: int | None = None
    priority: int | None = None


@dataclass
class ZramDevice:
    name: str | None = None
    disksize_bytes: int | None = None
    comp_algorithm: str | None = None  # the active algorithm, if determinable


@dataclass
class MemoryPolicyInfo:
    swap_devices: list[SwapDevice] = field(default_factory=list)
    zram_devices: list[ZramDevice] = field(default_factory=list)
    #: Exact config-file paths found to actually declare a [zramN]
    #: section (not just "a directory exists") — see memory_policy.py.
    #: Empty means genuinely unconfigured.
    zram_generator_config_sources: list[str] = field(default_factory=list)
    #: True when more than one real source was found — Serein does not
    #: attempt to resolve final precedence, it just avoids proposing a
    #: second, competing configuration on top of an already-ambiguous one.
    zram_generator_config_ambiguous: bool = False


@dataclass(frozen=True)
class ZramCapability:
    """The single source of truth for "can Serein manage ZRAM here" —
    shared by ``capabilities.py`` (reports it directly) and
    ``planner.py`` (gates ``memory.zram`` on it), so the two can never
    diverge. See ``memory_policy.detect_zram_capability``."""

    available: bool
    confidence: str  # "high" | "medium" | "low"
    mechanism: str
    reason: str


@dataclass
class StorageSchedulerInfo:
    name: str | None = None
    current_scheduler: str | None = None
    available_schedulers: list[str] = field(default_factory=list)


@dataclass
class StoragePolicyInfo:
    devices: list[StorageSchedulerInfo] = field(default_factory=list)


@dataclass
class BatteryStatus:
    name: str | None = None
    capacity_percent: int | None = None
    status: str | None = None  # "Charging" | "Discharging" | "Full" | "Unknown" | None


@dataclass
class PowerPolicyInfo:
    ppd_present: bool = False  # power-profiles-daemon service/binary detected
    batteries: list[BatteryStatus] = field(default_factory=list)


@dataclass(frozen=True)
class GPUClassification:
    """A single device's confidence-scored classification — distinct
    from GPUDevice.kind (S0, schema-locked, structural-evidence-only):
    this may also weigh the boot_vga heuristic. See gpu_policy.py."""

    vendor: str | None
    kind: str  # "integrated" | "discrete" | "unknown"
    confidence: str  # "high" | "medium" | "low"


@dataclass
class GPUPolicyInfo:
    #: True/False only when topology evidence is sufficient; None means
    #: genuinely unresolved (e.g. multiple GPUs, at least one unknown) -
    #: never guessed.
    hybrid: bool | None = False
    hybrid_confidence: str = "high"  # "high" | "medium" | "low"
    classifications: list[GPUClassification] = field(default_factory=list)
    nvidia_present: bool = False
    nvidia_kernel_module_loaded: bool = False
    amdgpu_kernel_module_loaded: bool = False
    #: Counts only devices classified with sufficient confidence
    #: (kind != "unknown") - an "unknown" device contributes to neither.
    integrated_count: int = 0
    discrete_count: int = 0


@dataclass
class ThermalZoneInfo:
    zone_type: str | None = None
    temp_celsius: float | None = None


@dataclass
class ThermalInfo:
    zones: list[ThermalZoneInfo] = field(default_factory=list)
    hwmon_present: bool = False


@dataclass
class Capability:
    id: str
    available: bool | None  # None = genuinely unknown/ambiguous, not False
    mechanism: str | None
    confidence: str  # "high" | "medium" | "low"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilitiesReport:
    schema_version: int
    capabilities: list[Capability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass
class PlanAction:
    id: str
    component: str
    action: str
    target: str | None
    current: str | None
    reason: str
    confidence: str  # "high" | "medium" | "low"
    requires_root: bool
    reversible: bool
    risk: str  # "none" | "low" | "medium" | "high"
    verification: str
    status: str  # "APPLY" | "NOOP" | "SKIP" | "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HardwarePlan:
    schema_version: int
    profile_id: str
    profile_available: bool
    unavailable_reason: str | None
    actions: list[PlanAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_available": self.profile_available,
            "unavailable_reason": self.unavailable_reason,
            "actions": [a.to_dict() for a in self.actions],
        }
