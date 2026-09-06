"""PyTorch detection and backend-variant identification.

Uses a bounded, injectable subprocess probe against whatever
``python3`` resolves to on PATH — never an in-process ``import torch``
inside Serein's own control-plane process (S4 brief Section 60/61).
Merely importing torch in a *child* process is an ordinary, safe,
read-only operation (it loads shared libraries but does not touch GPU
hardware); what this module deliberately never does is call
``torch.cuda.is_available()`` or any other API that would actually
initialize a CUDA/ROCm context — that can hang or crash on a broken
driver, and reflects *runtime* usability, not the static build-variant
question this module answers. See docs/ai/pytorch-strategy.md and
docs/ai/known-limitations.md for this documented scope boundary.
"""

from __future__ import annotations

import json

from serein.ai.models import (
    AIBackendInfo,
    AmdStatus,
    IntelAIStatus,
    NvidiaStatus,
    PyTorchBackendDecision,
    PyTorchStatus,
)
from serein.development.models import ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner

_TORCH_PROBE = (
    "import json\n"
    "try:\n"
    "    import torch\n"
    "except ImportError:\n"
    "    raise SystemExit(1)\n"
    "info = {\n"
    "    'version': torch.__version__,\n"
    "    'cuda': getattr(torch.version, 'cuda', None),\n"
    "    'hip': getattr(torch.version, 'hip', None),\n"
    "}\n"
    "print(json.dumps(info))\n"
)


def detect_pytorch_status(runner: CommandRunner = DEFAULT_RUNNER) -> PyTorchStatus:
    result = runner.run(["python3", "-c", _TORCH_PROBE], timeout=10.0)
    if result is None or result.returncode != 0:
        return PyTorchStatus(installed=ToolStatus(id="torch", installed=False))

    try:
        info = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return PyTorchStatus(installed=ToolStatus(id="torch", installed=False))

    version = info.get("version")
    cuda_version = info.get("cuda")
    hip_version = info.get("hip")

    if cuda_version:
        backend, backend_version = "cuda", cuda_version
    elif hip_version:
        backend, backend_version = "rocm", hip_version
    else:
        backend, backend_version = "cpu", None

    return PyTorchStatus(
        installed=ToolStatus(id="torch", installed=True, version=version),
        build_backend=backend,
        build_backend_version=backend_version,
    )


def select_pytorch_backend(
    backend: AIBackendInfo, nvidia: NvidiaStatus, amd: AmdStatus, intel: IntelAIStatus
) -> PyTorchBackendDecision:
    """The single shared "which PyTorch backend should be planned"
    decision (S4R Section 4/9) — a hardware backend *candidate*
    (``backend.primary``) is never enough on its own to select an
    accelerator-specific PyTorch build. Consumed identically by
    ``planner.py`` and ``capabilities.py`` so they can never derive
    incompatible conclusions.

    ``status="BLOCKED"`` is returned whenever an accelerator hardware
    candidate exists but its runtime/framework-compatibility could not
    be confirmed — Serein does not silently fall back to a CPU build
    in that case (that would hide the real, resolvable blocker from
    the user) and does not guess an unproven accelerator build either.
    """
    if backend.primary == "nvidia_cuda":
        if nvidia.driver_version is not None:
            return PyTorchBackendDecision(
                target="cuda", status="APPLY", confidence="high",
                reason="NVIDIA driver proven working (nvidia-smi responds). "
                "Prebuilt PyTorch CUDA wheels bundle their own required CUDA "
                "userspace runtime libraries - a local CUDA Toolkit is not "
                "required for this (see docs/ai/pytorch-strategy.md).",
            )
        return PyTorchBackendDecision(
            target="cuda", status="BLOCKED", confidence="low",
            reason="NVIDIA hardware exists but CUDA runtime usability is not "
            "yet established because a working driver is missing. Serein "
            "will not select a CUDA PyTorch build until nvidia.driver "
            "resolves; CPU inference remains independently available via "
            "inference.ollama/inference.llama_cpp.",
        )
    if backend.primary == "amd_rocm":
        if amd.rocm_support.gpu_enumerated is True:
            return PyTorchBackendDecision(
                target="rocm", status="BLOCKED", confidence="low",
                reason="ROCm's own runtime enumerates a GPU agent (real "
                "evidence this hardware is ROCm-capable), but PyTorch's own "
                "ROCm-wheel/MIOpen compatibility for this exact GPU/"
                "framework combination is a separate question Serein cannot "
                "independently confirm - see docs/ai/amd-rocm-strategy.md.",
            )
        if amd.rocm_support.gpu_enumerated is False:
            return PyTorchBackendDecision(
                target="cpu", status="APPLY", confidence="high",
                reason="ROCm's own runtime confirmed no GPU agent on this "
                "hardware; CPU is the correct target.",
            )
        return PyTorchBackendDecision(
            target="rocm", status="BLOCKED", confidence="low",
            reason="AMD hardware detected, but ROCm support for this exact "
            "GPU cannot be confirmed without ROCm's own tooling installed - "
            "Serein does not guess from vendor ID alone.",
        )
    if backend.primary == "intel_gpu":
        return PyTorchBackendDecision(
            target="xpu", status="BLOCKED", confidence="low",
            reason="Intel GPU detected, but PyTorch's native XPU backend "
            "compatibility for this hardware is not currently verified by "
            "Serein - see docs/ai/intel-strategy.md.",
        )
    if backend.primary == "unknown":
        return PyTorchBackendDecision(
            target="cpu", status="APPLY", confidence="medium",
            reason="GPU vendor could not be classified into a known "
            "backend; Serein does not select an accelerator-specific "
            "PyTorch build without knowing what it is. CPU remains "
            "available.",
        )
    return PyTorchBackendDecision(
        target="cpu", status="APPLY", confidence="high",
        reason="No GPU detected. CPU is a fully supported, first-class target.",
    )
