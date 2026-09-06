"""``serein ai status``: a read-only AI-workstation summary.

Safe to run anywhere (Windows dev host, Ubuntu, WSL, CI, a container) —
every field degrades to an honest "unavailable"/"unknown" rather than
raising. Reuses the existing ``ai`` profile entry from the profile
registry (S2) rather than introducing a second profile concept
(Section 88 - one profile file, hardware and software layers both
described in it, exactly like S3 extended ``dev``).
"""

from __future__ import annotations

from pathlib import Path

from serein.ai.amd import detect_amd_status
from serein.ai.backend import classify_backend
from serein.ai.containers import detect_ai_container_status
from serein.ai.inference import detect_inference_status
from serein.ai.intel import detect_intel_status
from serein.ai.models import AIStatusReport
from serein.ai.nvidia import detect_nvidia_status
from serein.ai.python_env import detect_python_ai_packages
from serein.ai.pytorch import detect_pytorch_status, select_pytorch_backend
from serein.ai.storage import build_ai_storage_info
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.gpu import detect_gpus
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.profiles.registry import list_profiles


def build_ai_status(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> AIStatusReport:
    profiles = {p.id: p for p in list_profiles()}
    ai_profile = profiles.get("ai")

    gpus = detect_gpus(root)
    gpu_policy = detect_gpu_policy(root, gpus)
    backend = classify_backend(gpus, gpu_policy)

    nvidia = detect_nvidia_status(gpu_policy, runner=runner, root=root)
    amd = detect_amd_status(gpu_policy, runner=runner)
    intel = detect_intel_status(gpu_policy)
    pytorch = detect_pytorch_status(runner=runner)

    return AIStatusReport(
        schema_version=1,
        profile_id="ai",
        profile_status=ai_profile.status if ai_profile else "declared",
        backend=backend,
        nvidia=nvidia,
        amd=amd,
        intel=intel,
        pytorch=pytorch,
        pytorch_decision=select_pytorch_backend(backend, nvidia, amd, intel),
        python_packages=detect_python_ai_packages(runner=runner),
        inference=detect_inference_status(runner=runner),
        containers=detect_ai_container_status(runner=runner, root=root),
        storage=build_ai_storage_info(),
    )
