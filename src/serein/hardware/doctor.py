"""``serein hardware doctor``: hardware-layer diagnostics.

Reuses ``serein.doctor.models`` (same PASS/WARN/FAIL/SKIP model as the S0
foundation doctor and the S1 desktop doctor) so ``--json`` validates
against the existing ``schemas/doctor-report.schema.json`` with no new
schema needed. Absence of hardware (no battery, no NVIDIA GPU, no ZRAM)
is never a FAIL — only a Serein-claimed-but-broken configuration would be,
and S2 has no Apply step yet, so FAIL is reserved for genuine detection
failures (an exception, or a plan that cannot be generated at all).
"""

from __future__ import annotations

from pathlib import Path

from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.planner import VALID_PROFILES, build_hardware_plan
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.resources import RESOURCES, missing_resources

_REPORT_CHECK = ("hardware_report_integrity", "Hardware report integrity")
_CPU_CHECK = ("hardware_cpu_topology", "CPU topology detection")
_MEMORY_CHECK = ("hardware_memory_detection", "Memory detection")
_STORAGE_CHECK = ("hardware_storage_detection", "Storage detection")
_POWER_CHECK = ("hardware_power_consistency", "Power-source consistency")
_ZRAM_CHECK = ("hardware_existing_zram", "Existing ZRAM detection")
_GPU_TOPOLOGY_CHECK = ("hardware_gpu_topology_confidence", "GPU topology confidence")
_PLAN_CHECK = ("hardware_profile_plan_generation", "Hardware profile plan generation")
_VIRT_GUARD_CHECK = ("hardware_virtualization_guard", "Virtualization guard consistency")
_RESOURCES_CHECK = ("hardware_required_resources", "Hardware policy resources present")


def _check_report_integrity(root: Path) -> CheckResult:
    check_id, title = _REPORT_CHECK
    try:
        probe_hardware(root)
    except Exception as exc:  # pragma: no cover - probe_hardware already degrades internally
        return CheckResult(check_id, title, CheckStatus.FAIL, f"Hardware probe raised: {exc}")
    detail = "Hardware probe completed without error."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_cpu_topology(root: Path) -> CheckResult:
    check_id, title = _CPU_CHECK
    hw = probe_hardware(root)
    if hw.cpu.logical_cores:
        detail = f"{hw.cpu.logical_cores} logical CPU(s) detected."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    detail = "CPU core count could not be determined."
    return CheckResult(check_id, title, CheckStatus.WARN, detail)


def _check_memory_detection(root: Path) -> CheckResult:
    check_id, title = _MEMORY_CHECK
    hw = probe_hardware(root)
    if hw.memory.total_bytes:
        gib = hw.memory.total_bytes / (1024**3)
        return CheckResult(check_id, title, CheckStatus.PASS, f"{gib:.1f} GiB of RAM detected.")
    detail = "Total RAM could not be determined."
    return CheckResult(check_id, title, CheckStatus.WARN, detail)


def _check_storage_detection(root: Path) -> CheckResult:
    check_id, title = _STORAGE_CHECK
    hw = probe_hardware(root)
    if hw.environment.is_container:
        detail = "Not meaningful inside a container."
        return CheckResult(check_id, title, CheckStatus.SKIP, detail)
    if hw.storage:
        detail = f"{len(hw.storage)} storage device(s) detected."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    detail = "No storage devices detected."
    return CheckResult(check_id, title, CheckStatus.WARN, detail)


def _check_power_consistency(root: Path) -> CheckResult:
    check_id, title = _POWER_CHECK
    hw = probe_hardware(root)
    if not hw.power.has_battery:
        detail = "No battery (desktop-class host)."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    power_policy = detect_power_policy(root)
    if any(b.capacity_percent is None for b in power_policy.batteries):
        detail = "Battery present but its capacity is unreadable."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    detail = "Battery present and its state is readable."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_existing_zram(root: Path) -> CheckResult:
    check_id, title = _ZRAM_CHECK
    memory_policy = detect_memory_policy(root)
    if memory_policy.zram_generator_config_ambiguous:
        sources = ", ".join(memory_policy.zram_generator_config_sources)
        detail = f"Multiple ZRAM configuration sources found ({sources}); treating conservatively."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    if memory_policy.zram_devices or memory_policy.zram_generator_config_sources:
        detail = "Existing ZRAM implementation detected; Serein will not propose a second one."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    detail = "No ZRAM configured yet."
    return CheckResult(check_id, title, CheckStatus.SKIP, detail)


def _check_gpu_topology_confidence(root: Path) -> CheckResult:
    check_id, title = _GPU_TOPOLOGY_CHECK
    hw = probe_hardware(root)
    if not hw.gpu:
        detail = "No GPU detected."
        return CheckResult(check_id, title, CheckStatus.SKIP, detail)
    gpu_policy = detect_gpu_policy(root, hw.gpu)
    if gpu_policy.hybrid is None:
        detail = (
            f"{len(hw.gpu)} GPU(s) detected but topology could not be confidently "
            "resolved (no PCI ID database is consulted by design)."
        )
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    detail = f"GPU topology resolved with {gpu_policy.hybrid_confidence} confidence."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_plan_generation(root: Path) -> CheckResult:
    check_id, title = _PLAN_CHECK
    try:
        for profile_id in VALID_PROFILES:
            build_hardware_plan(profile_id, root)
    except Exception as exc:
        detail = f"Plan generation raised for a profile: {exc}"
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    detail = f"All {len(VALID_PROFILES)} hardware profile plans generated without error."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_virtualization_guard(root: Path) -> CheckResult:
    check_id, title = _VIRT_GUARD_CHECK
    hw = probe_hardware(root)
    if not (hw.environment.virtualization == "wsl" or hw.environment.is_container):
        detail = "Not running in WSL or a container."
        return CheckResult(check_id, title, CheckStatus.SKIP, detail)
    plan = build_hardware_plan("balanced", root)
    cpu_action = next((a for a in plan.actions if a.id == "cpu.epp"), None)
    if cpu_action is not None and cpu_action.status == "SKIP":
        detail = "CPU policy actions correctly SKIP under virtualization/container guard."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    detail = "Virtualization/container guard did not force CPU policy actions to SKIP."
    return CheckResult(check_id, title, CheckStatus.FAIL, detail)


def _check_required_resources(_root: Path) -> CheckResult:
    check_id, title = _RESOURCES_CHECK
    missing = missing_resources()
    if missing:
        names = ", ".join(r.id for r in missing)
        detail = f"Missing shipped resource(s): {names}."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    detail = f"All {len(RESOURCES)} shipped resources present."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


_ALL_CHECKS = (
    _check_report_integrity,
    _check_cpu_topology,
    _check_memory_detection,
    _check_storage_detection,
    _check_power_consistency,
    _check_existing_zram,
    _check_gpu_topology_confidence,
    _check_plan_generation,
    _check_virtualization_guard,
    _check_required_resources,
)


def run_hardware_checks(root: Path = DEFAULT_ROOT) -> DoctorReport:
    checks = [check(root) for check in _ALL_CHECKS]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
