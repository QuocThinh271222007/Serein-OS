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
from serein.ai.pytorch import detect_pytorch_status
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

    capabilities.append(
        Capability(
            "cuda_toolkit", True, nvidia.cuda_toolkit_installed,
            nvidia.cuda_toolkit_installed if nvidia.hardware_present else None,
            "nvcc / /usr/local/cuda marker", "ubuntu-repository", "high",
            "Detected independently of the driver's CUDA version - see "
            "docs/ai/nvidia-strategy.md.",
        )
    )

    capabilities.append(
        Capability(
            "rocm_runtime", amd.hardware_present, amd.rocminfo.installed,
            amd.rocm_support.supported, "rocminfo", "ubuntu-repository",
            amd.rocm_support.confidence, amd.rocm_support.reason,
        )
    )

    capabilities.append(
        Capability(
            "intel_gpu_runtime", intel.hardware_present, False, None, None, None, "low",
            "Intel AI compute stack maturity not currently verified end-to-end "
            "by Serein - see docs/ai/intel-strategy.md."
            if intel.hardware_present else "No Intel GPU detected.",
        )
    )

    capabilities.append(
        Capability(
            "pytorch", True, pytorch.installed.installed, pytorch.installed.installed,
            "importlib subprocess probe", "python-package-index", "high",
            "Detected against whatever python3 resolves to on PATH - a "
            "project .venv must be active for Serein to see it.",
        )
    )

    nvidia_backend_present = any(c.backend == "nvidia_cuda" for c in backend.candidates)
    capabilities.append(
        Capability(
            "pytorch_cuda", nvidia_backend_present,
            pytorch.installed.installed and pytorch.build_backend == "cuda", None,
            "python-package-index index URL", "python-package-index", "medium",
            "torch.cuda.is_available() is never called by Serein (S4 brief "
            "Section 8/61); only the static build variant is reported.",
        )
    )

    amd_backend_present = any(c.backend == "amd_rocm" for c in backend.candidates)
    capabilities.append(
        Capability(
            "pytorch_rocm", amd_backend_present,
            pytorch.installed.installed and pytorch.build_backend == "rocm", None,
            "python-package-index index URL", "python-package-index", "medium",
            "Runtime usability not verified, same reasoning as pytorch_cuda.",
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
        ai_container_usable = container_installed and containers.nvidia_container_toolkit.installed
        reason = (
            "GPU container passthrough requires both a container engine and "
            "the NVIDIA Container Toolkit (current CDI-based mechanism)."
        )
    else:
        ai_container_usable = container_installed
        reason = "No NVIDIA backend candidate; a plain container engine suffices."
    capabilities.append(
        Capability(
            "ai_container_runtime", True, container_installed, ai_container_usable,
            "podman/docker + nvidia-ctk", "ubuntu-repository", "medium", reason,
        )
    )

    return AICapabilitiesReport(
        schema_version=AI_CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities
    )
