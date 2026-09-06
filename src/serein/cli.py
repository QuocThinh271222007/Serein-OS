"""Serein control-plane CLI entry point.

Built on ``argparse`` only — see ``docs/adr/0003-control-plane-language.md``
for why S0 avoids a CLI framework dependency. Every command here is
read-only: S0 defines the installer/mutation contract in
``docs/architecture/installer-contract.md`` but implements no mutation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from serein import __version__
from serein.core.status import build_status_report
from serein.desktop.config import RESOURCES, missing_resources
from serein.desktop.doctor import run_desktop_checks
from serein.desktop.plan import build_desktop_plan
from serein.desktop.status import build_desktop_status
from serein.doctor.checks import run_checks
from serein.doctor.models import CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.capabilities import build_capabilities
from serein.hardware.cpu_policy import detect_cpu_policy
from serein.hardware.doctor import run_hardware_checks
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.planner import VALID_PROFILES, build_hardware_plan
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.storage_policy import detect_storage_policy
from serein.hardware.thermal import detect_thermal
from serein.profiles.registry import list_profiles

_CAPABILITY_LABELS = {
    "cpu_governor_control": "CPU governor control",
    "cpu_epp_control": "CPU EPP control",
    "zram_configurable": "ZRAM configurable",
    "swap_exists": "Swap exists",
    "storage_scheduler_configurable": "Storage scheduler configurable",
    "battery_detected": "Battery detected",
    "power_profile_control": "Power profile control",
    "nvidia_compute_gpu": "NVIDIA compute GPU",
    "gpu_switching": "GPU switching",
    "thermal_telemetry": "Thermal telemetry",
}


def _yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _format_bytes(n: int | None) -> str:
    if n is None:
        return "unavailable"
    gib = n / (1024**3)
    return f"{gib:.1f} GiB"


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    status = build_status_report()
    print("SEREIN")
    print(f"Version:              {status.version}")
    print(f"Host compatibility:   {status.os_compatibility}")
    print(f"Kernel release:       {status.kernel_release or 'unavailable'}")
    print(f"Architecture:         {status.architecture or 'unavailable'}")
    cpu = f"{status.cpu_vendor or 'unknown vendor'} {status.cpu_model or ''}".strip()
    print(f"CPU:                  {cpu or 'unavailable'}")
    print(f"Logical CPUs:         {status.logical_cpus if status.logical_cpus else 'unavailable'}")
    print(f"RAM:                  {_format_bytes(status.memory_total_bytes)}")
    print(f"GPU:                  {', '.join(status.gpu_summary)}")
    print(f"Virtualization:       {status.virtualization}")
    print(f"Current profile:      {status.current_profile}")
    return 0


def _print_doctor_report(header: str, report: DoctorReport) -> None:
    print(header)
    for check in report.checks:
        marker = {
            CheckStatus.PASS: "PASS",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
            CheckStatus.SKIP: "SKIP",
        }[check.status]
        print(f"[{marker:4}] {check.title}: {check.detail}")

    summary = report.summary
    print(
        "Summary: "
        f"{summary['PASS']} pass, {summary['WARN']} warn, "
        f"{summary['FAIL']} fail, {summary['SKIP']} skip"
    )


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = run_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN DOCTOR", report)
    return report.exit_code


def _cmd_hardware_probe(args: argparse.Namespace) -> int:
    report = probe_hardware()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN HARDWARE PROBE")
    print(f"OS:              {report.os.pretty_name or 'unavailable'}")
    print(f"Kernel:          {report.kernel.release or 'unavailable'}")
    print(f"Architecture:    {report.cpu.architecture or 'unavailable'}")
    cpu = f"{report.cpu.vendor or 'unknown vendor'} {report.cpu.model_name or ''}".strip()
    print(f"CPU:             {cpu or 'unavailable'}")
    print(
        "Cores:           "
        f"{report.cpu.physical_cores or '?'} physical / {report.cpu.logical_cores or '?'} logical"
    )
    print(f"Memory total:    {_format_bytes(report.memory.total_bytes)}")
    if report.gpu:
        for gpu in report.gpu:
            print(f"GPU:             {gpu.vendor or 'unknown'} ({gpu.kind or 'unknown'})")
    else:
        print("GPU:             unavailable")
    if report.storage:
        for device in report.storage:
            print(
                f"Storage:         {device.name} [{device.device_class}] "
                f"{_format_bytes(device.size_bytes)}"
            )
    else:
        print("Storage:         unavailable")
    print(f"Battery:         {'present' if report.power.has_battery else 'not present'}")
    print(f"Virtualization:  {report.environment.virtualization}")
    return 0


def _cmd_hardware_status(_args: argparse.Namespace) -> int:
    hw = probe_hardware()
    cpu_policy = detect_cpu_policy(DEFAULT_ROOT)
    memory_policy = detect_memory_policy(DEFAULT_ROOT)
    storage_policy = detect_storage_policy(DEFAULT_ROOT)
    power_policy = detect_power_policy(DEFAULT_ROOT)
    gpu_policy = detect_gpu_policy(DEFAULT_ROOT, hw.gpu)
    thermal = detect_thermal(DEFAULT_ROOT)

    print("SEREIN HARDWARE")
    print()
    print("CPU")
    cpu_label = f"{hw.cpu.vendor or 'unknown vendor'} {hw.cpu.model_name or ''}".strip()
    print(f"  {cpu_label or 'unavailable'}")
    print(f"  Driver        {cpu_policy.driver or 'not detected'}")
    print(f"  Governor      {cpu_policy.governor or 'not detected'}")
    print(f"  EPP           {cpu_policy.epp_current or 'not available'}")
    print()
    print("Memory")
    print(f"  RAM           {_format_bytes(hw.memory.total_bytes)}")
    disk_swap = [s for s in memory_policy.swap_devices if s.kind != "zram"]
    if disk_swap:
        total = sum(s.size_bytes or 0 for s in disk_swap)
        print(f"  Swap          {_format_bytes(total)} ({len(disk_swap)} device(s))")
    else:
        print("  Swap          none")
    if memory_policy.zram_devices:
        zram = memory_policy.zram_devices[0]
        algo = zram.comp_algorithm or "unknown algorithm"
        print(f"  ZRAM          {_format_bytes(zram.disksize_bytes)} ({algo})")
    else:
        print("  ZRAM          not configured")
    print()
    print("Storage")
    if storage_policy.devices:
        for device in storage_policy.devices:
            print(f"  {device.name:<12}  scheduler={device.current_scheduler or 'unknown'}")
    else:
        print("  unavailable")
    print()
    print("Power")
    print(f"  Device        {'laptop' if hw.power.has_battery else 'desktop'}")
    if hw.power.on_ac_power is True:
        ac = "connected"
    elif hw.power.on_ac_power is False:
        ac = "not connected"
    else:
        ac = "unknown"
    print(f"  AC            {ac}")
    if power_policy.batteries:
        for battery in power_policy.batteries:
            if battery.capacity_percent is not None:
                pct = f"{battery.capacity_percent}%"
            else:
                pct = "unknown"
            print(f"  Battery       {pct} ({battery.status or 'unknown status'})")
    else:
        print("  Battery       not present")
    print()
    print("GPU")
    if hw.gpu:
        for gpu in hw.gpu:
            print(f"  {gpu.vendor or 'unknown'} ({gpu.kind or 'unknown'})")
    else:
        print("  unavailable")
    print(f"  Hybrid        {'yes' if gpu_policy.hybrid else 'no'}")
    print()
    print("Thermal")
    telemetry = "available" if (thermal.zones or thermal.hwmon_present) else "not available"
    print(f"  sensors       {telemetry}")
    return 0


def _cmd_hardware_doctor(args: argparse.Namespace) -> int:
    report = run_hardware_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN HARDWARE DOCTOR", report)
    return report.exit_code


def _cmd_hardware_capabilities(args: argparse.Namespace) -> int:
    report = build_capabilities()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN HARDWARE CAPABILITIES")
    print()
    for capability in report.capabilities:
        label = _CAPABILITY_LABELS.get(capability.id, capability.id)
        print(f"{label:<32}{_yes_no_unknown(capability.available)}")
    return 0


def _cmd_hardware_plan(args: argparse.Namespace) -> int:
    plan = build_hardware_plan(args.profile)
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    print(f"SEREIN HARDWARE PLAN - {plan.profile_id}")
    print()
    if not plan.profile_available:
        print(f"Profile available: no ({plan.unavailable_reason})")
        return 0
    print("Profile available: yes")
    print()
    print("Actions:")
    for step in plan.actions:
        target = f" -> {step.target}" if step.target else ""
        current = f" (current: {step.current})" if step.current else ""
        print(f"  [{step.status:<7}] {step.component}.{step.action}{target}{current}")
        print(f"            reason: {step.reason}")
        print(
            f"            risk: {step.risk} | reversible: {'yes' if step.reversible else 'no'} | "
            f"requires_root: {'yes' if step.requires_root else 'no'}"
        )
        print(f"            verify: {step.verification}")
    return 0


def _cmd_profile_list(args: argparse.Namespace) -> int:
    profiles = list_profiles()
    if args.json:
        print(json.dumps([p.to_dict() for p in profiles], indent=2, sort_keys=True))
        return 0

    print("SEREIN PROFILES")
    print(f"{'ID':<12}{'STATUS':<13}{'ACTIVE':<8}NAME")
    for profile in profiles:
        active = "yes" if profile.active else "no"
        print(f"{profile.id:<12}{profile.status:<13}{active:<8}{profile.name}")
    print()
    print("Note: profile activation is not implemented in S0; ACTIVE is always 'no'.")
    return 0


def _cmd_desktop_status(_args: argparse.Namespace) -> int:
    status = build_desktop_status()
    print("SEREIN DESKTOP")
    print()
    print(f"Profile        {status.profile_id}")
    print(f"Implementation {status.profile_status}")
    print()
    print("Session")
    print(f"  Desktop      {status.session.desktop_environment or 'unavailable'}")
    print(f"  Type         {status.session.session_type or 'unavailable'}")
    kwin = status.availability.kwin_wayland_installed or status.availability.kwin_x11_installed
    print(f"  KWin         {'detected' if kwin else 'unavailable'}")
    print(f"  SDDM         {'detected' if status.availability.sddm_installed else 'unavailable'}")
    print()
    print("Configuration")
    applied = "yes" if status.config.serein_preset_applied else "no"
    print(f"  Serein preset applied    {applied}")
    print()
    print("Compatibility")
    print(f"  Ubuntu target            {status.os_compatibility}")
    return 0


def _cmd_desktop_doctor(args: argparse.Namespace) -> int:
    report = run_desktop_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN DESKTOP DOCTOR", report)
    return report.exit_code


def _cmd_desktop_plan(args: argparse.Namespace) -> int:
    plan = build_desktop_plan()
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    print("Desktop installation plan")
    print()
    print("Packages:")
    for pkg in plan.packages:
        print(f"  install {pkg}")
    print()
    print("System configuration:")
    for step in plan.system_configuration:
        print(f"  {step.action:<24} {step.detail}")
    print()
    print("User configuration:")
    for step in plan.user_configuration:
        print(f"  {step.action:<28} {step.detail}")
    print()
    print("Verification:")
    for check_id in plan.verification:
        print(f"  {check_id}")
    return 0


def _cmd_desktop_config_status(_args: argparse.Namespace) -> int:
    missing = {r.id for r in missing_resources()}
    print("SEREIN DESKTOP CONFIG RESOURCES")
    for resource in RESOURCES:
        state = "MISSING" if resource.id in missing else "present"
        print(f"[{state:7}] {resource.id:<22} -> {resource.target_path}")
    print()
    print("'present' means the file ships in this repository under desktop/;")
    print("it does not mean the file has been installed onto this host.")
    return 1 if missing else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serein", description="Serein OS control-plane CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Print the control-plane version").set_defaults(
        func=_cmd_version
    )
    subparsers.add_parser("status", help="Show a read-only workstation summary").set_defaults(
        func=_cmd_status
    )

    doctor_parser = subparsers.add_parser("doctor", help="Run foundation-level diagnostics")
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    doctor_parser.set_defaults(func=_cmd_doctor)

    hardware_parser = subparsers.add_parser("hardware", help="Hardware discovery")
    hardware_subparsers = hardware_parser.add_subparsers(dest="hardware_command", required=True)
    probe_parser = hardware_subparsers.add_parser("probe", help="Probe available hardware")
    probe_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    probe_parser.set_defaults(func=_cmd_hardware_probe)

    hardware_status_parser = hardware_subparsers.add_parser(
        "status", help="Show a read-only hardware policy summary"
    )
    hardware_status_parser.set_defaults(func=_cmd_hardware_status)

    hardware_doctor_parser = hardware_subparsers.add_parser(
        "doctor", help="Run hardware-level diagnostics"
    )
    hardware_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    hardware_doctor_parser.set_defaults(func=_cmd_hardware_doctor)

    hardware_capabilities_parser = hardware_subparsers.add_parser(
        "capabilities", help="Show what Serein can safely control on this host"
    )
    hardware_capabilities_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    hardware_capabilities_parser.set_defaults(func=_cmd_hardware_capabilities)

    hardware_plan_parser = hardware_subparsers.add_parser(
        "plan", help="Show the hardware resource-policy plan for a profile"
    )
    hardware_plan_parser.add_argument("profile", choices=VALID_PROFILES)
    hardware_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    hardware_plan_parser.set_defaults(func=_cmd_hardware_plan)

    profile_parser = subparsers.add_parser("profile", help="Profile management")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_list_parser = profile_subparsers.add_parser("list", help="List known profiles")
    profile_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    profile_list_parser.set_defaults(func=_cmd_profile_list)

    desktop_parser = subparsers.add_parser("desktop", help="Desktop (KDE Plasma) integration")
    desktop_subparsers = desktop_parser.add_subparsers(dest="desktop_command", required=True)

    desktop_subparsers.add_parser("status", help="Show desktop state").set_defaults(
        func=_cmd_desktop_status
    )

    desktop_doctor_parser = desktop_subparsers.add_parser(
        "doctor", help="Run desktop-level diagnostics"
    )
    desktop_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    desktop_doctor_parser.set_defaults(func=_cmd_desktop_doctor)

    desktop_plan_parser = desktop_subparsers.add_parser(
        "plan", help="Show the desktop installation plan"
    )
    desktop_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    desktop_plan_parser.set_defaults(func=_cmd_desktop_plan)

    desktop_config_parser = desktop_subparsers.add_parser("config", help="Desktop config resources")
    desktop_config_subparsers = desktop_config_parser.add_subparsers(
        dest="desktop_config_command", required=True
    )
    desktop_config_subparsers.add_parser(
        "status", help="Show which desktop config resources ship in this repository"
    ).set_defaults(func=_cmd_desktop_config_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # last-resort guard: no command may traceback at users
        print(f"serein: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
