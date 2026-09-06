"""``serein hardware capabilities``: what Serein can safely control here,
as distinct from ``serein hardware probe`` (what hardware exists).

Every capability reports ``available`` (``True``/``False``, or ``None``
when genuinely ambiguous — never a guessed boolean), ``mechanism``
(the sysfs/service path checked), ``confidence``, and ``reason``. WSL and
container guests never report governor/EPP/scheduler control as available
even when a stray sysfs file happens to be readable, since ownership of
those mechanisms belongs to the host, not the guest — see
docs/hardware/architecture.md.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT, read_text
from serein.hardware.cpu_policy import detect_cpu_policy
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.models import (
    CAPABILITIES_SCHEMA_VERSION,
    CapabilitiesReport,
    Capability,
    EnvironmentInfo,
    ZramDevice,
)
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.storage_policy import detect_storage_policy
from serein.hardware.thermal import detect_thermal

_ZRAM_GENERATOR_BINARY = ("usr", "lib", "systemd", "system-generators", "zram-generator")


def _virtualized(environment: EnvironmentInfo) -> bool:
    return environment.virtualization == "wsl" or environment.is_container


def _zram_kernel_support(root: Path, existing_zram_devices: list[ZramDevice]) -> bool:
    """Real, checkable evidence that the kernel can create zram devices
    on demand - not an assumption. ``/sys/class/zram-control`` is the
    kernel's own hot-add/hot-remove control interface (present once the
    zram module is loaded or built in); a "zram" line in /proc/modules,
    or an already-existing /sys/block/zram* device, are equally valid
    independent signals."""
    if (root / "sys" / "class" / "zram-control").is_dir():
        return True
    if existing_zram_devices:
        return True
    modules_text = read_text(root / "proc" / "modules")
    if modules_text:
        for line in modules_text.splitlines():
            fields = line.split()
            if fields and fields[0] == "zram":
                return True
    return False


def build_capabilities(root: Path = DEFAULT_ROOT) -> CapabilitiesReport:
    hw = probe_hardware(root)
    environment = hw.environment
    cpu_policy = detect_cpu_policy(root)
    memory_policy = detect_memory_policy(root)
    storage_policy = detect_storage_policy(root)
    power_policy = detect_power_policy(root)
    gpu_policy = detect_gpu_policy(root, hw.gpu)
    thermal = detect_thermal(root)

    virtualized = _virtualized(environment)
    virt_label = environment.virtualization if environment.virtualization == "wsl" else "container"
    virt_reason = (
        f"Running under {virt_label}: this mechanism is controlled by the host, not this guest."
    )

    capabilities: list[Capability] = []

    if virtualized:
        capabilities.append(
            Capability(
                "cpu_governor_control",
                False,
                "sysfs:/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
                "high",
                virt_reason,
            )
        )
    else:
        capabilities.append(
            Capability(
                "cpu_governor_control",
                cpu_policy.cpufreq_present,
                "sysfs:/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
                "high",
                "cpufreq sysfs interface detected."
                if cpu_policy.cpufreq_present
                else "No cpufreq sysfs interface on this system.",
            )
        )

    if virtualized:
        capabilities.append(
            Capability(
                "cpu_epp_control",
                False,
                "sysfs:/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference",
                "high",
                virt_reason,
            )
        )
    else:
        has_epp = bool(cpu_policy.epp_available)
        capabilities.append(
            Capability(
                "cpu_epp_control",
                has_epp,
                "sysfs:/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference",
                "high",
                "energy_performance_preference is exposed by this CPU/driver."
                if has_epp
                else "This CPU/driver does not expose an EPP knob "
                "(older acpi-cpufreq or no HWP support).",
            )
        )

    # S2R correction: this was unconditionally True, which overclaimed
    # control in containers/WSL and asserted a write path that had never
    # actually been checked for. Live validation (docs/validation/s2r/
    # zram-validation.md) confirmed systemd-zram-generator's own
    # generator refuses to create devices under container-detected
    # virtualization (which includes WSL2) - so "false" here for those
    # environments is now a verified fact, not a guess.
    if virtualized:
        capabilities.append(
            Capability(
                "zram_configurable",
                False,
                "systemd-zram-generator",
                "high",
                f"Running under {virt_label}: systemd-zram-generator's own generator "
                "declines to create devices when systemd-detect-virt reports a "
                "container context (verified behavior, includes WSL2).",
            )
        )
    else:
        kernel_support = _zram_kernel_support(root, memory_policy.zram_devices)
        capabilities.append(
            Capability(
                "zram_configurable",
                kernel_support,
                "sysfs:/sys/class/zram-control (kernel), systemd-zram-generator (config mechanism)",
                "high" if kernel_support else "medium",
                "The kernel's zram-control hot-add interface (or an existing zram "
                "device/module) confirms zram support is present."
                if kernel_support
                else "No zram-control interface, loaded zram module, or existing zram "
                "device was found; kernel support could not be confirmed.",
            )
        )

    has_swap = bool(memory_policy.swap_devices or memory_policy.zram_devices)
    capabilities.append(
        Capability(
            "swap_exists",
            has_swap,
            "/proc/swaps",
            "high",
            f"{len(memory_policy.swap_devices) + len(memory_policy.zram_devices)} active swap "
            "backend(s) found." if has_swap else "No active swap backend found.",
        )
    )

    if virtualized:
        capabilities.append(
            Capability(
                "storage_scheduler_configurable",
                False,
                "sysfs:/sys/block/<dev>/queue/scheduler",
                "high",
                virt_reason,
            )
        )
    else:
        schedulable = any(d.available_schedulers for d in storage_policy.devices)
        capabilities.append(
            Capability(
                "storage_scheduler_configurable",
                schedulable,
                "sysfs:/sys/block/<dev>/queue/scheduler",
                "high",
                "At least one storage device exposes a configurable I/O scheduler."
                if schedulable
                else "No storage device exposes a queue/scheduler sysfs interface.",
            )
        )

    capabilities.append(
        Capability(
            "battery_detected",
            bool(power_policy.batteries),
            "/sys/class/power_supply/*/type",
            "high",
            f"{len(power_policy.batteries)} battery/batteries present."
            if power_policy.batteries
            else "No battery power_supply device found.",
        )
    )

    capabilities.append(
        Capability(
            "power_profile_control",
            power_policy.ppd_present,
            "power-profiles-daemon (service unit / powerprofilesctl)",
            "medium",
            "power-profiles-daemon appears installed; its exact supported profile set "
            "(e.g. whether 'performance' exists) can only be read over D-Bus, which "
            "Serein does not query in S2." if power_policy.ppd_present
            else "power-profiles-daemon was not found on this host.",
        )
    )

    capabilities.append(
        Capability(
            "nvidia_compute_gpu",
            gpu_policy.nvidia_present,
            "/sys/class/drm (PCI vendor 0x10de)",
            "high",
            "An NVIDIA GPU is present." if gpu_policy.nvidia_present else "No NVIDIA GPU detected.",
        )
    )

    capabilities.append(
        Capability(
            "gpu_switching",
            None,
            None,
            "low",
            "No standard, safely-readable sysfs interface reliably indicates hybrid-GPU "
            "switching support (e.g. PRIME/switcheroo-control) without invoking vendor "
            "tooling; Serein does not execute external commands to detect this in S2.",
        )
    )

    has_thermal = bool(thermal.zones) or thermal.hwmon_present
    capabilities.append(
        Capability(
            "thermal_telemetry",
            has_thermal,
            "/sys/class/thermal, /sys/class/hwmon",
            "high",
            "Thermal zone(s) or hwmon sensor(s) detected."
            if has_thermal
            else "No thermal_zone or hwmon sensor found.",
        )
    )

    return CapabilitiesReport(schema_version=CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities)
