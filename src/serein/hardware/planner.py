"""``serein hardware plan <profile>``: deterministic, evidence-based hardware
resource policy planning.

No Apply mechanism exists in S2 (see docs/hardware/architecture.md) — this
module only ever reads state (via the other ``hardware.*_policy`` modules)
and proposes ``PlanAction``s with an explicit ``status`` of
``APPLY``/``NOOP``/``SKIP``/``BLOCKED``. Nothing here writes to sysfs, calls
a package manager, or talks to D-Bus. A plan is a pure function of on-disk
machine state: calling it twice against the same ``root`` yields identical
output.

Profiles describe *resource policy*, not application installation — the
``ai`` profile does not install CUDA (S4's job); it only biases CPU/power
policy toward a compute-heavy workload and reports GPU topology.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.cpu_policy import detect_cpu_policy
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.models import (
    PLAN_SCHEMA_VERSION,
    CPUPolicyInfo,
    EnvironmentInfo,
    GPUPolicyInfo,
    HardwarePlan,
    MemoryPolicyInfo,
    PlanAction,
    PowerInfo,
    PowerPolicyInfo,
    StoragePolicyInfo,
)
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.storage_policy import detect_storage_policy

VALID_PROFILES: tuple[str, ...] = ("balanced", "dev", "ai", "battery", "cyber")

# Serein profile -> upstream power-profiles-daemon profile. Only "battery"
# diverges from "balanced": whether PPD's own "performance" profile exists
# on this hardware cannot be verified without a D-Bus call (which Serein
# does not make in S2), so no Serein profile requests it here — the "ai"
# profile's performance bias instead rides entirely on the CPU EPP action
# below, which *is* backed by real, directly-readable sysfs evidence.
_PPD_PROFILE_MAP: dict[str, str] = {
    "balanced": "balanced",
    "dev": "balanced",
    "cyber": "balanced",
    "ai": "balanced",
    "battery": "power-saver",
}

_ZRAM_TARGET_DESCRIPTION = (
    "zram-size=min(ram/2, 4096) (upstream default, pinned explicitly), "
    "swap-priority=100 (also upstream default), compression-algorithm left "
    "unset (kernel default) - see hardware/defaults/zram-generator.conf"
)


def _virtualized(environment: EnvironmentInfo) -> bool:
    return environment.virtualization == "wsl" or environment.is_container


def _virt_label(environment: EnvironmentInfo) -> str:
    return "WSL" if environment.virtualization == "wsl" else "container"


def _epp_candidates(profile_id: str, power: PowerInfo) -> list[str]:
    on_ac_or_desktop = power.on_ac_power is True or not power.has_battery
    if profile_id == "ai":
        if on_ac_or_desktop:
            return ["performance", "balance_performance"]
        return ["balance_performance"]
    if profile_id == "battery":
        return ["balance_power", "power"]
    if profile_id in ("dev", "cyber", "balanced"):
        return ["balance_performance", "default", "balance_power"]
    return ["default"]


def _cpu_action(profile_id: str, cpu_policy: CPUPolicyInfo, environment: EnvironmentInfo,
                 power: PowerInfo) -> PlanAction:
    action_id, component, action = "cpu.epp", "cpu", "set_epp"

    if _virtualized(environment):
        return PlanAction(
            action_id, component, action, None, cpu_policy.epp_current,
            f"{_virt_label(environment)} environment: CPU energy-performance policy is "
            "controlled by the host, not this guest.",
            "high", False, True, "none", "n/a", "SKIP",
        )
    if not cpu_policy.cpufreq_present:
        return PlanAction(
            action_id, component, action, None, None,
            "No cpufreq sysfs interface on this system.",
            "high", False, True, "none", "n/a", "SKIP",
        )
    if not cpu_policy.epp_available:
        return PlanAction(
            action_id, component, action, None, cpu_policy.governor,
            "This CPU/driver does not expose energy_performance_preference "
            "(e.g. acpi-cpufreq without HWP support).",
            "high", False, True, "none", "n/a", "SKIP",
        )

    candidates = _epp_candidates(profile_id, power)
    target = next((c for c in candidates if c in cpu_policy.epp_available), None)
    verify = "cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"

    if target is None:
        return PlanAction(
            action_id, component, action, candidates[0], cpu_policy.epp_current,
            f"None of the preferred values ({', '.join(candidates)}) for the '{profile_id}' "
            f"profile are in this CPU's available list ({', '.join(cpu_policy.epp_available)}).",
            "medium", True, True, "low", verify, "BLOCKED",
        )
    if cpu_policy.epp_current == target:
        return PlanAction(
            action_id, component, action, target, cpu_policy.epp_current,
            f"Already at the '{profile_id}' profile's preferred EPP value.",
            "high", False, True, "none", verify, "NOOP",
        )
    return PlanAction(
        action_id, component, action, target, cpu_policy.epp_current,
        f"'{profile_id}' profile prefers energy_performance_preference='{target}'.",
        "high", True, True, "low", verify, "APPLY",
    )


def _power_profile_action(profile_id: str, power_policy: PowerPolicyInfo) -> PlanAction:
    action_id, component, action = "power.ppd_profile", "power", "set_power_profile"
    if not power_policy.ppd_present:
        return PlanAction(
            action_id, component, action, None, None,
            "power-profiles-daemon not detected on this host.",
            "high", False, True, "none", "n/a", "SKIP",
        )
    target = _PPD_PROFILE_MAP[profile_id]
    return PlanAction(
        action_id, component, action, target, None,
        f"Maps Serein's '{profile_id}' profile to upstream power-profiles-daemon '{target}'.",
        "medium", True, True, "none",
        "powerprofilesctl get (or the ActiveProfile D-Bus property) after apply",
        "APPLY",
    )


def _zram_action(
    ram_bytes: int | None, memory_policy: MemoryPolicyInfo, environment: EnvironmentInfo
) -> PlanAction:
    action_id, component, action = "memory.zram", "memory", "configure_zram"

    if memory_policy.zram_devices:
        detail = (
            f"An active ZRAM device already exists ({memory_policy.zram_devices[0].name}); "
            "Serein will not layer a second, competing implementation."
        )
        return PlanAction(
            action_id, component, action, None, "device present", detail,
            "high", False, True, "none",
            "cat /sys/block/zram0/comp_algorithm", "NOOP",
        )
    if memory_policy.zram_generator_config_sources:
        sources = ", ".join(memory_policy.zram_generator_config_sources)
        note = " (multiple sources - precedence not resolved by Serein)" if (
            memory_policy.zram_generator_config_ambiguous
        ) else ""
        detail = f"Existing zram-generator configuration found at: {sources}{note}."
        return PlanAction(
            action_id, component, action, None, "config present", detail,
            "high", False, True, "none",
            "cat /sys/block/zram0/comp_algorithm", "NOOP",
        )
    if _virtualized(environment):
        return PlanAction(
            action_id, component, action, None, "not configured",
            f"{_virt_label(environment)} environment: systemd-zram-generator itself "
            "declines to create devices under container-detected virtualization "
            "(verified behavior, see docs/validation/s2r/zram-validation.md) - "
            "proposing configuration here would never take effect.",
            "high", False, True, "none", "n/a", "SKIP",
        )
    if ram_bytes is None:
        return PlanAction(
            action_id, component, action, _ZRAM_TARGET_DESCRIPTION, "not configured",
            "RAM size could not be determined; ZRAM cannot be sized safely without it.",
            "low", False, True, "none", "n/a", "BLOCKED",
        )
    return PlanAction(
        action_id, component, action, _ZRAM_TARGET_DESCRIPTION, "not configured",
        "No existing ZRAM implementation detected; proposing upstream "
        "systemd-zram-generator defaults sized to this host's RAM.",
        "high", True, True, "low",
        "systemctl status systemd-zram-setup@zram0.service; cat /sys/block/zram0/disksize",
        "APPLY",
    )


def _storage_actions(
    storage_policy: StoragePolicyInfo, environment: EnvironmentInfo
) -> list[PlanAction]:
    component, action = "storage", "set_scheduler"
    actions: list[PlanAction] = []
    virtualized = _virtualized(environment)

    for device in storage_policy.devices:
        action_id = f"storage.scheduler.{device.name}"
        verify = f"cat /sys/block/{device.name}/queue/scheduler"

        if virtualized:
            actions.append(PlanAction(
                action_id, component, action, None, device.current_scheduler,
                f"{_virt_label(environment)} environment: I/O scheduling is host-controlled.",
                "high", False, True, "none", "n/a", "SKIP",
            ))
            continue
        if not device.available_schedulers:
            actions.append(PlanAction(
                action_id, component, action, None, device.current_scheduler,
                "No queue/scheduler sysfs interface for this device (common for virtual "
                "or mapped block devices).",
                "high", False, True, "none", "n/a", "SKIP",
            ))
            continue

        # S2R correction: S2 proposed switching NVMe devices to the "none"
        # scheduler whenever available. That was speculative tuning with
        # no Serein-specific benchmark evidence behind it (S8 owns
        # measurement) - removed. Every device with a real scheduler
        # interface, on any bus, is left exactly as the kernel/upstream
        # set it. Detection (current/available schedulers) is preserved
        # for a future S8 benchmark pass to consume.
        actions.append(PlanAction(
            action_id, component, action, device.current_scheduler, device.current_scheduler,
            "No measured Serein-specific evidence justifies replacing the current "
            "upstream scheduler (see docs/hardware/storage-policy.md).",
            "high", False, True, "none", verify, "NOOP",
        ))

    return actions


def _gpu_action(profile_id: str, gpu_policy: GPUPolicyInfo) -> PlanAction:
    action_id, component, action = "gpu.compute_topology", "gpu", "report_topology"
    has_discrete = gpu_policy.discrete_count > 0 or gpu_policy.nvidia_kernel_module_loaded

    if profile_id == "ai":
        reason = (
            "Discrete/compute-capable GPU detected; CPU and GPU policy both apply "
            "(the actual CUDA/ROCm runtime is S4 scope, not S2)."
            if has_discrete
            else "No discrete GPU detected; the AI profile's CPU/memory policy still "
            "applies for a CPU-only workload - the profile is not invalidated by GPU absence."
        )
        return PlanAction(action_id, component, action, None, None, reason,
                           "high", False, True, "none", "n/a", "NOOP")

    if profile_id == "battery" and gpu_policy.hybrid is True:
        return PlanAction(
            action_id, component, action, None, None,
            "Hybrid graphics detected; the battery profile prefers integrated graphics "
            "where the desktop environment already supports it. Serein does not force "
            "GPU switching, unload drivers, or kill sessions in S2.",
            gpu_policy.hybrid_confidence, False, True, "none", "n/a", "NOOP",
        )
    if profile_id == "battery" and gpu_policy.hybrid is None:
        return PlanAction(
            action_id, component, action, None, None,
            "Multiple GPUs detected but topology could not be confidently resolved "
            "(no PCI ID database is consulted - see docs/hardware/gpu-policy.md); "
            "no GPU-specific preference is expressed for this profile.",
            "low", False, True, "none", "n/a", "NOOP",
        )

    return PlanAction(action_id, component, action, None, None,
                       "No GPU-specific policy change for this profile.",
                       "high", False, True, "none", "n/a", "NOOP")


def build_hardware_plan(profile_id: str, root: Path = DEFAULT_ROOT) -> HardwarePlan:
    if profile_id not in VALID_PROFILES:
        raise ValueError(f"unknown hardware profile: {profile_id!r}")

    hw = probe_hardware(root)

    if profile_id == "battery" and not hw.power.has_battery:
        return HardwarePlan(
            schema_version=PLAN_SCHEMA_VERSION,
            profile_id=profile_id,
            profile_available=False,
            unavailable_reason="No battery detected on this host.",
            actions=[],
        )

    cpu_policy = detect_cpu_policy(root)
    memory_policy = detect_memory_policy(root)
    storage_policy = detect_storage_policy(root)
    power_policy = detect_power_policy(root)
    gpu_policy = detect_gpu_policy(root, hw.gpu)

    actions = [
        _cpu_action(profile_id, cpu_policy, hw.environment, hw.power),
        _power_profile_action(profile_id, power_policy),
        _zram_action(hw.memory.total_bytes, memory_policy, hw.environment),
        *_storage_actions(storage_policy, hw.environment),
        _gpu_action(profile_id, gpu_policy),
    ]

    return HardwarePlan(
        schema_version=PLAN_SCHEMA_VERSION,
        profile_id=profile_id,
        profile_available=True,
        unavailable_reason=None,
        actions=actions,
    )
