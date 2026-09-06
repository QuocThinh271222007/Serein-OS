"""``serein ai capabilities``: which AI stacks Serein can safely
provision/manage, and whether the underlying hardware/runtime is
actually *usable* — distinct from ``serein ai status``'s "what already
exists" (mirrors S3's status/capabilities split exactly, Section 86).

Every capability's ``usable`` field is the three-layer distinction the
S4 brief repeatedly requires (Section 6/7): hardware presence is not
runtime readiness is not confirmed usability. ``usable=None`` always
means genuinely unverified — never guessed True to make a report look
more complete.
"""

from __future__ import annotations

from pathlib import Path

from serein.ai.amd import detect_amd_status
from serein.ai.backend import classify_backend
from serein.ai.containers import detect_ai_container_status
from serein.ai.inference import detect_inference_status
from serein.ai.intel import detect_intel_status
from serein.ai.models import (
    AI_CAPABILITIES_SCHEMA_VERSION,
    AICapabilitiesReport,
)
from serein.ai.models import AICapability as Capability
from serein.ai.nvidia import detect_nvidia_status
from serein.ai.python_env import detect_python_ai_packages
from serein.ai.pytorch import detect_pytorch_status, select_pytorch_backend
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.gpu import detect_gpus
from serein.hardware.gpu_policy import detect_gpu_policy


def build_ai_capabilities(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> AICapabilitiesReport:
    gpus = detect_gpus(root)
    gpu_policy = detect_gpu_policy(root, gpus)
    backend = classify_backend(gpus, gpu_policy)

    nvidia = detect_nvidia_status(gpu_policy, runner=runner, root=root)
    amd = detect_amd_status(gpu_policy, runner=runner)
    intel = detect_intel_status(gpu_policy)
    pytorch = detect_pytorch_status(runner=runner)
    py_packages = detect_python_ai_packages(runner=runner)
    inference = detect_inference_status(runner=runner)
    containers = detect_ai_container_status(runner=runner, root=root)

    capabilities: list[Capability] = []

    capabilities.append(
        Capability(
            "nvidia_hardware", True, nvidia.hardware_present, None,
            "sysfs (/sys/class/drm)", "ubuntu-repository", "high",
            "Hardware presence only - does not imply a driver or CUDA "
            "runtime is ready.",
        )
    )

    if not nvidia.hardware_present:
        capabilities.append(
            Capability(
                "nvidia_driver", False, False, None, None, None, "high",
                "No NVIDIA hardware detected.",
            )
        )
    elif nvidia.driver_version is not None:
        capabilities.append(
            Capability(
                "nvidia_driver", True, True, True, "nvidia-smi",
                "ubuntu-repository", "high",
                f"nvidia-smi reports a working driver (version {nvidia.driver_version}).",
            )
        )
    else:
        capabilities.append(
            Capability(
                "nvidia_driver", True, False, False, "nvidia-smi",
                "ubuntu-repository", "high",
                "NVIDIA hardware detected but nvidia-smi did not report a "
                "working driver.",
            )
        )

    if not nvidia.hardware_present:
        capabilities.append(
            Capability(
                "cuda_runtime", False, False, None, None, None, "high",
                "No NVIDIA hardware detected.",
            )
        )
    else:
        cuda_runtime_present = nvidia.cuda_driver_api_version is not None
        capabilities.append(
            Capability(
                "cuda_runtime", True, cuda_runtime_present, cuda_runtime_present,
                "nvidia-smi (driver-reported)", "ubuntu-repository", "high",
                "The driver's own CUDA driver-API version, NOT proof a CUDA "
                "Toolkit is installed (see cuda_toolkit).",
            )
        )

    marker_only = nvidia.cuda_toolkit_marker_present and not nvidia.cuda_toolkit_installed
    capabilities.append(
        Capability(
            "cuda_toolkit", True, nvidia.cuda_toolkit_installed,
            nvidia.cuda_toolkit_installed if nvidia.hardware_present else None,
            "nvcc / dpkg cuda-toolkit package state", "ubuntu-repository", "high",
            (
                "A /usr/local/cuda marker exists but is not, by itself, "
                "proof of installation (nvcc/dpkg found nothing) - possibly "
                "stale or incomplete." if marker_only else
                "Detected independently of the driver's CUDA version, via "
                "nvcc or real dpkg package state - never a bare "
                "/usr/local/cuda marker alone. See docs/ai/nvidia-strategy.md."
            ),
        )
    )

    capabilities.append(
        Capability(
            "rocm_runtime", amd.hardware_present, amd.rocm_support.runtime_installed,
            amd.rocm_support.gpu_enumerated, "rocminfo", "ubuntu-repository",
            amd.rocm_support.confidence, amd.rocm_support.reason,
        )
    )

    capabilities.append(
        Capability(
            "intel_gpu_runtime", intel.hardware_present, False, None, None, None, "low",
            "PyTorch's native XPU backend compatibility for this hardware is "
            "not currently verified by Serein (Intel Extension for PyTorch "
            "is not Serein's recommended path) - see "
            "docs/ai/intel-strategy.md."
            if intel.hardware_present else "No Intel GPU detected.",
        )
    )

    pytorch_decision = select_pytorch_backend(backend, nvidia, amd, intel)

    capabilities.append(
        Capability(
            "pytorch", True, pytorch.installed.installed, pytorch.installed.installed,
            "importlib subprocess probe", "python-package-index", "high",
            "Detected against whatever python3 resolves to on PATH - a "
            "project .venv must be active for Serein to see it.",
        )
    )

    # Section 41 invariant: usable is only ever True for a build variant
    # that matches select_pytorch_backend()'s own confirmed-ready decision
    # - never derived independently of it.
    nvidia_backend_present = any(c.backend == "nvidia_cuda" for c in backend.candidates)
    cuda_installed = pytorch.installed.installed and pytorch.build_backend == "cuda"
    cuda_ready = pytorch_decision.target == "cuda" and pytorch_decision.status == "APPLY"
    capabilities.append(
        Capability(
            "pytorch_cuda", nvidia_backend_present, cuda_installed,
            (True if (cuda_installed and cuda_ready) else (False if cuda_installed else None)),
            "python-package-index index URL", "python-package-index", "medium",
            "torch.cuda.is_available() is never called by Serein (S4 brief "
            "Section 8/61); usable reflects select_pytorch_backend()'s "
            "runtime-gated decision, never the hardware candidate alone.",
        )
    )

    amd_backend_present = any(c.backend == "amd_rocm" for c in backend.candidates)
    rocm_installed = pytorch.installed.installed and pytorch.build_backend == "rocm"
    rocm_ready = pytorch_decision.target == "rocm" and pytorch_decision.status == "APPLY"
    capabilities.append(
        Capability(
            "pytorch_rocm", amd_backend_present, rocm_installed,
            (True if (rocm_installed and rocm_ready) else (False if rocm_installed else None)),
            "python-package-index index URL", "python-package-index", "medium",
            "ROCm GPU enumeration alone never implies PyTorch-ROCm "
            "framework compatibility; usable reflects "
            "select_pytorch_backend()'s conservative decision.",
        )
    )

    cpu_build_installed = pytorch.installed.installed and pytorch.build_backend == "cpu"
    capabilities.append(
        Capability(
            "pytorch_cpu", True, cpu_build_installed, cpu_build_installed,
            "python-package-index", "python-package-index", "high",
            "A CPU PyTorch build has no external runtime dependency beyond "
            "the interpreter - usable if installed.",
        )
    )

    capabilities.append(
        Capability(
            "ollama", True, inference.ollama.binary.installed,
            inference.ollama.binary.installed, "official-upstream-binary",
            "official-upstream-binary", "high",
            "A responding `ollama --version` is direct evidence of a working binary.",
        )
    )

    llama_cpp_installed = (
        inference.llama_cpp.llama_cli.installed or inference.llama_cpp.llama_server.installed
    )
    capabilities.append(
        Capability(
            "llama_cpp", True, llama_cpp_installed, llama_cpp_installed,
            "official-upstream-binary", "official-upstream-binary", "high",
            "Ollama and llama.cpp may coexist; neither is required for the other.",
        )
    )

    capabilities.append(
        Capability(
            "vllm", True, py_packages.vllm.installed, None,
            "python-package-index", "python-package-index", "medium",
            "vLLM's practical requirements are primarily CUDA + Linux; "
            "runtime usability on this specific hardware is not verified.",
        )
    )

    capabilities.append(
        Capability(
            "onnxruntime", True, py_packages.onnxruntime.installed,
            py_packages.onnxruntime.installed or None,
            "python-package-index", "python-package-index", "medium",
            "CPU execution provider assumed usable if installed; GPU "
            "execution-provider selection is not verified.",
        )
    )

    capabilities.append(
        Capability(
            "tensorrt", nvidia_backend_present, py_packages.tensorrt.installed, None,
            "NVIDIA's own pip index", "python-package-index", "low",
            "NVIDIA-specific and optional; only ever planned when compatible "
            "with the detected CUDA/driver stack.",
        )
    )

    container_installed = containers.podman.installed or containers.docker.installed
    if nvidia_backend_present:
        # Full GPU-container usability requires every link in the chain:
        # a working driver, a container engine, the NVIDIA Container
        # Toolkit, and real CDI integration evidence - engine+toolkit
        # alone is not sufficient (S4R Section 25/26/29).
        driver_ready = nvidia.driver_version is not None
        toolkit_installed = containers.nvidia_container_toolkit.installed
        cdi_evidenced = containers.cdi_nvidia_generated
        ai_container_usable = (
            driver_ready and container_installed and toolkit_installed and cdi_evidenced
        )
        if not driver_ready:
            reason = (
                "NVIDIA driver not confirmed working; GPU container "
                "passthrough cannot be usable without it."
            )
        elif not container_installed:
            reason = "No container engine installed."
        elif not toolkit_installed:
            reason = "NVIDIA Container Toolkit not installed."
        elif not cdi_evidenced:
            reason = (
                "No CDI integration evidence found (neither a spec file "
                "nor `nvidia-ctk cdi list`)."
            )
        else:
            reason = (
                "Driver, container engine, NVIDIA Container Toolkit, and "
                "CDI integration all confirmed."
            )
    else:
        ai_container_usable = container_installed
        reason = "No NVIDIA backend candidate; a plain container engine suffices."
    capabilities.append(
        Capability(
            "ai_container_runtime", True, container_installed, ai_container_usable,
            "podman/docker + nvidia-ctk + CDI", "ubuntu-repository", "medium", reason,
        )
    )

    return AICapabilitiesReport(
        schema_version=AI_CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities
    )
