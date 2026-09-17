"""``serein installer doctor``: Installer-layer diagnostics (S7.1
Section 23).

Reuses ``serein.doctor.models`` (same PASS/WARN/FAIL/SKIP model as
every other subsystem's doctor). No installer backend tooling installed
is PASS/SKIP, never FAIL - ``curtin``/Subiquity are normally only
present inside the live/install environment itself, never on a regular
development host, so their absence here is expected, not a defect
(mirrors ``serein.veil.doctor``'s "no Tor/Whonix tooling is PASS/SKIP,
never FAIL" philosophy). FAIL is reserved for a genuinely broken
structural state - plan construction/validation itself raising, or the
safety-gate logic disagreeing with its own invariants.
"""

from __future__ import annotations

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.installer.diskguard import ancestor_disk
from serein.installer.models import DiskInfo, PartitionInfo, TargetDiskIdentity
from serein.installer.planner import build_install_plan, validate_plan

_CURTIN_CHECK = ("installer_curtin_available", "curtin (installer backend) availability")
_LSBLK_CHECK = ("installer_lsblk_available", "lsblk (disk probe) availability")
_PLAN_CHECK = ("installer_plan_generation", "Install plan construction/validation")
_ANCESTRY_CHECK = ("installer_ancestry_self_check", "Ancestor-disk parsing self-check")


def _check_curtin(runner: CommandRunner) -> CheckResult:
    check_id, title = _CURTIN_CHECK
    result = runner.run(["curtin", "--version"])
    if result is None or result.returncode != 0:
        return CheckResult(
            check_id, title, CheckStatus.SKIP,
            "curtin not found - expected outside a live/install environment.",
        )
    return CheckResult(
        check_id, title, CheckStatus.PASS, f"curtin available: {result.stdout.strip() or 'ok'}"
    )


def _check_lsblk(runner: CommandRunner) -> CheckResult:
    check_id, title = _LSBLK_CHECK
    result = runner.run(["lsblk", "--version"])
    if result is None or result.returncode != 0:
        return CheckResult(
            check_id, title, CheckStatus.SKIP, "lsblk not found - disk inventory will be empty."
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "lsblk is available.")


def _synthetic_target_disk() -> DiskInfo:
    return DiskInfo(
        device_path="/dev/sdz",
        canonical_path="/dev/sdz",
        kernel_name="sdz",
        model="Serein Doctor Synthetic Disk",
        serial="doctor-self-check-serial",
        wwn="0xdoctorselfcheck",
        size_bytes=64 * 1024 * 1024 * 1024,
        transport="usb",
        partitions=(
            PartitionInfo(device_path="/dev/sdz1"),
            PartitionInfo(device_path="/dev/sdz2"),
        ),
        target_eligible=True,
        protected=False,
        identity_confidence="high",
    )


def _check_plan_generation() -> CheckResult:
    check_id, title = _PLAN_CHECK
    try:
        disk = _synthetic_target_disk()
        identity = TargetDiskIdentity(
            serial=disk.serial, wwn=disk.wwn, model=disk.model,
            size_bytes=disk.size_bytes, observed_device_path=disk.device_path,
        )
        plan = build_install_plan(identity, disk.device_path, protected_disk_identities=())
        validated = validate_plan(plan, protected_device_paths=())
        if not validated.validation.valid:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"synthetic self-check plan failed validation: {validated.validation.reasons}",
            )
    except Exception as exc:  # noqa: BLE001 - any raise here is a real structural defect
        return CheckResult(
            check_id, title, CheckStatus.FAIL, f"plan construction/validation raised: {exc}"
        )
    return CheckResult(
        check_id, title, CheckStatus.PASS,
        "Baseline plan construction and validation completed without error.",
    )


def _check_ancestry_self_check() -> CheckResult:
    check_id, title = _ANCESTRY_CHECK
    cases = (
        ("/dev/sdb1", "/dev/sdb"),
        ("/dev/nvme0n1p1", "/dev/nvme0n1"),
        ("/dev/mmcblk0p2", "/dev/mmcblk0"),
        ("/dev/nvme0n1", "/dev/nvme0n1"),
    )
    for device, expected in cases:
        actual = ancestor_disk(device)
        if actual != expected:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"ancestor_disk({device!r}) == {actual!r}, expected {expected!r}",
            )
    return CheckResult(check_id, title, CheckStatus.PASS, "Ancestor-disk parsing is correct.")


def run_installer_checks(runner: CommandRunner = DEFAULT_RUNNER) -> DoctorReport:
    checks = [
        _check_curtin(runner),
        _check_lsblk(runner),
        _check_plan_generation(),
        _check_ancestry_self_check(),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
