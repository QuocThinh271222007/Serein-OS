"""Foundation-level diagnostic checks.

Deliberately narrow in scope for S0: these validate that Serein *itself*
can reason about the host (supported OS family/arch, a working Python
runtime, functioning probes, valid schemas) — not whether any future
capability (CUDA, containers, desktop) is present. See
``docs/architecture/doctor-contract.md``.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT, is_real_root
from serein.hardware.probe import probe_hardware

_SUPPORTED_ARCHITECTURES = {"x86_64", "amd64"}
_MIN_PYTHON = (3, 12)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _check_os_family(root: Path) -> CheckResult:
    system = platform.system()
    if system == "Linux":
        return CheckResult(
            "os_family", "Operating system family", CheckStatus.PASS, "Linux detected."
        )
    return CheckResult(
        "os_family",
        "Operating system family",
        CheckStatus.FAIL,
        f"Serein targets Ubuntu Linux; detected '{system}'.",
    )


def _check_architecture(root: Path) -> CheckResult:
    machine = platform.machine().lower()
    if machine in _SUPPORTED_ARCHITECTURES:
        return CheckResult(
            "architecture", "CPU architecture", CheckStatus.PASS, f"{machine} is supported."
        )
    return CheckResult(
        "architecture",
        "CPU architecture",
        CheckStatus.WARN,
        f"'{machine}' is not the S0 target (x86_64); untested.",
    )


def _check_python_runtime(root: Path) -> CheckResult:
    if sys.version_info[:2] >= _MIN_PYTHON:
        return CheckResult(
            "python_runtime",
            "Python runtime",
            CheckStatus.PASS,
            f"Python {platform.python_version()} satisfies >= 3.12.",
        )
    return CheckResult(
        "python_runtime",
        "Python runtime",
        CheckStatus.FAIL,
        f"Python {platform.python_version()} is older than the required 3.12.",
    )


def _check_proc_available(root: Path) -> CheckResult:
    if platform.system() != "Linux" and is_real_root(root):
        return CheckResult(
            "proc_available", "/proc availability", CheckStatus.SKIP, "Not applicable off Linux."
        )
    if (root / "proc").is_dir():
        return CheckResult(
            "proc_available", "/proc availability", CheckStatus.PASS, "/proc is mounted."
        )
    return CheckResult(
        "proc_available",
        "/proc availability",
        CheckStatus.WARN,
        "/proc is unavailable; hardware detail will be limited.",
    )


def _check_sys_available(root: Path) -> CheckResult:
    if platform.system() != "Linux" and is_real_root(root):
        return CheckResult(
            "sys_available", "/sys availability", CheckStatus.SKIP, "Not applicable off Linux."
        )
    if (root / "sys").is_dir():
        return CheckResult(
            "sys_available", "/sys availability", CheckStatus.PASS, "/sys is mounted."
        )
    return CheckResult(
        "sys_available",
        "/sys availability",
        CheckStatus.WARN,
        "/sys is unavailable; GPU/storage/power detail will be limited.",
    )


def _check_schema_validity(root: Path) -> CheckResult:
    schema_dir = _REPO_ROOT / "schemas"
    expected = {
        "hardware-report.schema.json",
        "doctor-report.schema.json",
        "profile.schema.json",
    }
    if not schema_dir.is_dir():
        return CheckResult(
            "schema_validity", "Contract schemas", CheckStatus.SKIP, "Schema directory not found."
        )

    missing = expected - {p.name for p in schema_dir.glob("*.schema.json")}
    if missing:
        return CheckResult(
            "schema_validity",
            "Contract schemas",
            CheckStatus.FAIL,
            f"Missing schema file(s): {', '.join(sorted(missing))}.",
        )

    for name in expected:
        try:
            json.loads((schema_dir / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return CheckResult(
                "schema_validity",
                "Contract schemas",
                CheckStatus.FAIL,
                f"{name} is not valid JSON: {exc}",
            )

    return CheckResult(
        "schema_validity", "Contract schemas", CheckStatus.PASS, "All contract schemas parse."
    )


def _check_hardware_probe(root: Path) -> CheckResult:
    try:
        probe_hardware(root)
    except Exception as exc:  # pragma: no cover - probe_hardware already isolates failures
        return CheckResult(
            "hardware_probe",
            "Hardware probe",
            CheckStatus.FAIL,
            f"Hardware probe raised an exception: {exc}",
        )
    return CheckResult(
        "hardware_probe", "Hardware probe", CheckStatus.PASS, "Hardware probe completed."
    )


_ALL_CHECKS = (
    _check_os_family,
    _check_architecture,
    _check_python_runtime,
    _check_proc_available,
    _check_sys_available,
    _check_schema_validity,
    _check_hardware_probe,
)


def run_checks(root: Path = DEFAULT_ROOT) -> DoctorReport:
    return DoctorReport(
        schema_version=SCHEMA_VERSION, checks=[check(root) for check in _ALL_CHECKS]
    )
