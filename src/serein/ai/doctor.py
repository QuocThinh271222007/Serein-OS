"""``serein ai doctor``: AI-layer diagnostics.

Reuses ``serein.doctor.models`` (same PASS/WARN/FAIL/SKIP model as
S0/S1/S2/S3's doctors). No AI stack installed is PASS/SKIP, never
FAIL — S4 explicitly distinguishes "not provisioned" from
"misconfigured" from "unsupported" (Section 9): only a genuinely
broken/inconsistent state (e.g. conflicting toolkit indicators)
reaches WARN, and FAIL is reserved for a Serein-recorded/managed
component found broken (which S4 cannot produce yet, since no Apply
mechanism exists — so no check here can currently reach FAIL; it is
wired for when one can).
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.ai.amd import detect_amd_status
from serein.ai.backend import classify_backend
from serein.ai.containers import detect_ai_container_status
from serein.ai.models import AI_PYTHON_PACKAGE_SOURCE
from serein.ai.nvidia import detect_nvidia_status
from serein.ai.packages import all_tools
from serein.ai.planner import VALID_COMPONENTS, build_ai_plan
from serein.development.models import ToolSourceType
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.gpu import detect_gpus
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.profiles.registry import DEFAULT_PROFILES_DIR

_PROFILE_CHECK = ("ai_profile_integrity", "AI profile integrity")
_MANIFEST_CHECK = ("ai_package_manifest", "AI package manifest integrity")
_PLAN_CHECK = ("ai_plan_generation", "AI plan generation")
_BACKEND_CHECK = ("ai_backend_consistency", "AI backend/hardware consistency")
_CUDA_TOOLKIT_CHECK = ("ai_cuda_toolkit_conflict", "Multiple CUDA Toolkit indicators")
_ROCM_UNSUPPORTED_CHECK = ("ai_rocm_unsupported_hardware", "ROCm unsupported-hardware state")
_CONTAINER_ENGINE_CHECK = ("ai_container_engine_conflict", "AI container engine conflicts")

_VALID_SOURCE_TYPES: set[ToolSourceType] = {
    "ubuntu-repository", "official-upstream-repository", "official-upstream-binary",
    "language-bootstrap-tool", "user-installed", "optional", AI_PYTHON_PACKAGE_SOURCE,
}


def _check_profile_integrity() -> CheckResult:
    check_id, title = _PROFILE_CHECK
    manifest_path = DEFAULT_PROFILES_DIR / "ai" / "ai.profile.json"
    if not manifest_path.is_file():
        detail = "profiles/ai/ai.profile.json is missing."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    try:
        json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        detail = f"ai.profile.json is not valid JSON: {exc}"
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "ai.profile.json parses.")


def _check_manifest() -> CheckResult:
    check_id, title = _MANIFEST_CHECK
    tools = all_tools()
    ids = [t.id for t in tools]
    if len(ids) != len(set(ids)):
        detail = "Duplicate tool ids in the AI manifest."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    unrecognized = [t.id for t in tools if t.source_type not in _VALID_SOURCE_TYPES]
    if unrecognized:
        detail = f"Unrecognized source_type for: {', '.join(unrecognized)}."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, f"{len(tools)} tool(s) declared.")


def _check_plan_generation(root: Path, runner: CommandRunner) -> CheckResult:
    check_id, title = _PLAN_CHECK
    try:
        build_ai_plan(root=root, runner=runner)
        for component in VALID_COMPONENTS:
            build_ai_plan(component, root=root, runner=runner)
    except Exception as exc:
        return CheckResult(check_id, title, CheckStatus.FAIL, f"Plan generation raised: {exc}")
    detail = f"Full plan and all {len(VALID_COMPONENTS)} component plans generated without error."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_backend_consistency(root: Path) -> CheckResult:
    check_id, title = _BACKEND_CHECK
    gpus = detect_gpus(root)
    gpu_policy = detect_gpu_policy(root, gpus)
    backend = classify_backend(gpus, gpu_policy)
    if backend.primary == "unknown":
        detail = "GPU hardware present but its vendor could not be classified into a known backend."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    detail = f"Backend candidate: {backend.primary} (confidence {backend.primary_confidence})."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_cuda_toolkit_conflict(root: Path, runner: CommandRunner) -> CheckResult:
    check_id, title = _CUDA_TOOLKIT_CHECK
    gpus = detect_gpus(root)
    gpu_policy = detect_gpu_policy(root, gpus)
    nvidia = detect_nvidia_status(gpu_policy, runner=runner, root=root)
    if len(nvidia.cuda_toolkit_dirs) > 1:
        detail = f"Multiple CUDA Toolkit directories found: {', '.join(nvidia.cuda_toolkit_dirs)}."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "No conflicting CUDA Toolkit indicators.")


def _check_rocm_unsupported(root: Path, runner: CommandRunner) -> CheckResult:
    check_id, title = _ROCM_UNSUPPORTED_CHECK
    gpus = detect_gpus(root)
    gpu_policy = detect_gpu_policy(root, gpus)
    amd = detect_amd_status(gpu_policy, runner=runner)
    if amd.hardware_present and amd.rocm_support.supported is False:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "AMD GPU present but confirmed unsupported by the installed ROCm runtime.",
        )
    detail = "No confirmed-unsupported ROCm hardware state."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_container_engine_conflict(root: Path, runner: CommandRunner) -> CheckResult:
    check_id, title = _CONTAINER_ENGINE_CHECK
    containers = detect_ai_container_status(runner=runner, root=root)
    if containers.podman.installed and containers.docker.installed:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "Both Podman and Docker are installed; Serein will not choose one for you.",
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "No conflicting container engines.")


def run_ai_checks(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> DoctorReport:
    checks = [
        _check_profile_integrity(),
        _check_manifest(),
        _check_plan_generation(root, runner),
        _check_backend_consistency(root),
        _check_cuda_toolkit_conflict(root, runner),
        _check_rocm_unsupported(root, runner),
        _check_container_engine_conflict(root, runner),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
