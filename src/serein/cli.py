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
from serein.doctor.checks import run_checks
from serein.doctor.models import CheckStatus
from serein.hardware.probe import probe_hardware
from serein.profiles.registry import list_profiles


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


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = run_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    print("SEREIN DOCTOR")
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

    profile_parser = subparsers.add_parser("profile", help="Profile management")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_list_parser = profile_subparsers.add_parser("list", help="List known profiles")
    profile_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    profile_list_parser.set_defaults(func=_cmd_profile_list)

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
