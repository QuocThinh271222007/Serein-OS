"""``serein ai plan [component]``: deterministic, evidence-based AI
workstation planning.

No Apply mechanism exists in S4 (Section 12) - this module only ever
reads state (via the ``serein.ai.*``/``serein.development.*``
detectors) and proposes ``AIPlanAction``s with an explicit ``status``
of ``APPLY``/``NOOP``/``SKIP``/``BLOCKED``. Nothing here writes a
package, installs a driver, downloads a model, or touches GPU state.
A plan is a pure function of on-disk/PATH state: calling it twice
produces identical output.

Component filtering (``serein ai plan pytorch``) filters the one
canonical action list built here, mirroring S3's exact architecture
(Section 10/86) - it is never a separately-derived plan.
"""

from __future__ import annotations

from pathlib import Path

from serein.ai.amd import detect_amd_status
from serein.ai.backend import classify_backend
from serein.ai.containers import detect_ai_container_status
from serein.ai.inference import detect_inference_status
from serein.ai.models import (
    AI_PLAN_SCHEMA_VERSION,
    AIBackendInfo,
    AIContainerStatusInfo,
    AIPlan,
    AIPlanAction,
    AmdStatus,
    InferenceStatus,
    NvidiaStatus,
    PythonAIPackagesStatus,
    PyTorchStatus,
)
from serein.ai.nvidia import detect_nvidia_status
from serein.ai.python_env import detect_python_ai_packages
from serein.ai.pytorch import detect_pytorch_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment
from serein.hardware.gpu import detect_gpus
from serein.hardware.gpu_policy import detect_gpu_policy

VALID_COMPONENTS: tuple[str, ...] = ("pytorch", "inference", "containers", "voice")


def _driver_action(nvidia: NvidiaStatus, backend: AIBackendInfo) -> AIPlanAction:
    action_id, component, action = "nvidia.driver", "pytorch", "install_driver"
    if not nvidia.hardware_present:
        return AIPlanAction(
            action_id, component, action, "nvidia-driver", "ubuntu-repository",
            "not applicable", None,
            "No NVIDIA hardware detected.", False, True, "none", "n/a", "SKIP",
        )
    if nvidia.driver_version is not None:
        return AIPlanAction(
            action_id, component, action, "nvidia-driver", "ubuntu-repository",
            nvidia.driver_version, nvidia.driver_version,
            "A working NVIDIA driver is already present.", False, True, "none",
            "nvidia-smi", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action, "nvidia-driver", "ubuntu-repository",
        "not installed", "ubuntu-drivers-recommended",
        "NVIDIA hardware detected without a working driver. Serein recommends "
        "`ubuntu-drivers autoinstall`/Ubuntu's own packaged driver - never "
        "NVIDIA's .run installer (breaks Secure Boot/DKMS/kernel-update "
        "integration). Exact version is not hardcoded; see "
        "docs/ai/nvidia-strategy.md.",
        True, True, "medium", "nvidia-smi", "APPLY",
    )


def _cuda_toolkit_action(nvidia: NvidiaStatus) -> AIPlanAction:
    action_id, component, action = "nvidia.cuda_toolkit", "pytorch", "install_toolkit"
    if not nvidia.hardware_present:
        return AIPlanAction(
            action_id, component, action, "cuda-toolkit", "ubuntu-repository",
            "not applicable", None,
            "No NVIDIA hardware detected.", False, True, "none", "n/a", "SKIP",
        )
    if nvidia.cuda_toolkit_installed:
        return AIPlanAction(
            action_id, component, action, "cuda-toolkit", "ubuntu-repository",
            "installed", "installed",
            "A CUDA Toolkit installation was already detected (nvcc/marker).",
            False, True, "none", "nvcc --version", "NOOP",
        )
    if nvidia.driver_version is None:
        return AIPlanAction(
            action_id, component, action, "cuda-toolkit", "ubuntu-repository",
            "driver missing", None,
            "A working NVIDIA driver must be present before a CUDA Toolkit "
            "version can be safely chosen (compatibility depends on the "
            "driver) - see nvidia.driver.", False, True, "none", "n/a", "BLOCKED",
        )
    return AIPlanAction(
        action_id, component, action, "cuda-toolkit", "ubuntu-repository",
        "not installed", "compatible-current",
        "Ubuntu's own multiverse archive (verified live - see "
        "docs/validation/s4/ubuntu-package-validation.md); current CUDA "
        "Toolkit version chosen for driver/PyTorch/Ubuntu compatibility - "
        "never simply 'the newest one'. See docs/ai/nvidia-strategy.md.",
        True, True, "medium", "nvcc --version", "APPLY",
    )


def _pytorch_action(pytorch: PyTorchStatus, backend: AIBackendInfo) -> AIPlanAction:
    action_id, component, action = "python.pytorch", "pytorch", "install_package"
    if pytorch.installed.installed:
        return AIPlanAction(
            action_id, component, action, "torch", "python-package-index",
            f"{pytorch.build_backend or 'unknown'} build ({pytorch.installed.version})",
            None,
            "PyTorch is already installed (detected on the active python3's "
            "PATH). Serein does not install a second backend variant "
            "alongside it.", False, True, "none",
            "python3 -c \"import torch; print(torch.__version__)\"", "NOOP",
        )
    target_backend = {
        "nvidia_cuda": "cuda", "amd_rocm": "rocm", "intel_gpu": "cpu", "unknown": "cpu",
    }.get(backend.primary, "cpu")
    return AIPlanAction(
        action_id, component, action, "torch", "python-package-index",
        "not installed", f"{target_backend} build",
        f"Installed via `uv` from PyTorch's own {target_backend} index URL, "
        "into a project/AI environment - never system Python, never "
        "`sudo pip install torch`. Backend chosen from the classified AI "
        "backend candidate. See docs/ai/pytorch-strategy.md and ADR-0014.",
        False, True, "low", "python3 -c \"import torch\"", "APPLY",
    )


def _transformers_action(py_packages: PythonAIPackagesStatus) -> AIPlanAction:
    action_id, component, action = "python.transformers_baseline", "pytorch", "install_package"
    base = (py_packages.transformers, py_packages.accelerate,
            py_packages.safetensors, py_packages.huggingface_hub)
    missing = [t.id for t in base if not t.installed]
    if not missing:
        return AIPlanAction(
            action_id, component, action,
            "transformers, accelerate, safetensors, huggingface_hub",
            "python-package-index", "installed", "installed",
            "The Transformers baseline is already installed.", False, True,
            "none", "importlib.metadata probe", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action,
        "transformers, accelerate, safetensors, huggingface_hub",
        "python-package-index",
        "partially installed" if len(missing) < len(base) else "not installed",
        "transformers, accelerate, safetensors, huggingface_hub",
        f"Missing package(s): {', '.join(missing)}. Installed via `uv`, never "
        "system Python. datasets/peft/trl/bitsandbytes/flash-attn are "
        "optional and not part of this baseline.", False, True, "low",
        "importlib.metadata probe", "APPLY",
    )


def _rocm_action(amd: AmdStatus) -> AIPlanAction:
    """ROCm support (``amd.rocm_support.supported``) can only ever be
    confirmed True/False by ROCm's own tooling (``rocminfo``) actually
    running - which means it is only ever non-``None`` when ``rocminfo``
    is already installed. So there are really only two reachable
    states once AMD hardware is present: rocminfo already installed
    (NOOP - regardless of what it reports; an installed-but-unsupported
    combination is the doctor's ``ai_rocm_unsupported_hardware`` WARN
    to surface, not something reinstalling ROCm would fix), or
    rocminfo absent, in which case support is unconditionally unknown
    and Serein will not guess from vendor ID alone (BLOCKED)."""
    action_id, component, action = "amd.rocm", "pytorch", "install_runtime"
    if not amd.hardware_present:
        return AIPlanAction(
            action_id, component, action, "rocm", "ubuntu-repository",
            "not applicable", None, "No AMD hardware detected.", False, True,
            "none", "n/a", "SKIP",
        )
    if amd.rocminfo.installed:
        return AIPlanAction(
            action_id, component, action, "rocm", "ubuntu-repository",
            "installed", "installed", "ROCm tooling is already installed.",
            False, True, "none", "rocminfo", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action, "rocm", "ubuntu-repository",
        "unknown", None,
        "AMD hardware detected, but ROCm support for this exact GPU cannot "
        "be confirmed without ROCm's own tooling installed. Serein does not "
        "guess from vendor ID alone - see docs/ai/amd-rocm-strategy.md.",
        False, True, "none", "n/a", "BLOCKED",
    )


def _ollama_action(inference: InferenceStatus) -> AIPlanAction:
    action_id, component, action = "inference.ollama", "inference", "install_tool"
    if inference.ollama.binary.installed:
        return AIPlanAction(
            action_id, component, action, "ollama", "official-upstream-binary",
            inference.ollama.binary.version, inference.ollama.binary.version,
            "Ollama is already installed.", False, True, "none", "ollama --version", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action, "ollama", "official-upstream-binary",
        "not installed", "latest",
        "Official installer: ollama.com/install.sh (not executed by S4). "
        "Convenient model lifecycle/server UX; coexists with llama.cpp.",
        False, True, "low", "ollama --version", "APPLY",
    )


def _llama_cpp_action(inference: InferenceStatus) -> AIPlanAction:
    action_id, component, action = "inference.llama_cpp", "inference", "install_tool"
    cli, server = inference.llama_cpp.llama_cli, inference.llama_cpp.llama_server
    installed = cli.installed or server.installed
    if installed:
        return AIPlanAction(
            action_id, component, action, "llama.cpp", "official-upstream-binary",
            "installed", "installed", "llama.cpp is already installed.",
            False, True, "none", "llama-cli --version", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action, "llama.cpp", "official-upstream-binary",
        "not installed", "latest",
        "No official Ubuntu package - source build or a GitHub Releases "
        "prebuilt asset (documented, not executed). Lightweight, "
        "CPU/low-VRAM-friendly GGUF baseline; coexists with Ollama.",
        False, True, "low", "llama-cli --version", "APPLY",
    )


def _containers_action(
    containers: AIContainerStatusInfo, backend: AIBackendInfo, environment_is_container: bool
) -> AIPlanAction:
    action_id, component, action = "containers.engine", "containers", "install_apt_packages"
    if environment_is_container:
        return AIPlanAction(
            action_id, component, action, "podman", "ubuntu-repository", "not applicable",
            None, "Running inside a container: Serein does not plan a nested "
            "container engine here.", False, True, "none", "n/a", "SKIP",
        )
    if containers.podman.installed or containers.docker.installed:
        engines = [n for n, s in (("podman", containers.podman), ("docker", containers.docker))
                   if s.installed]
        return AIPlanAction(
            action_id, component, action, "podman", "ubuntu-repository",
            ", ".join(engines), ", ".join(engines),
            f"Container engine(s) already present ({', '.join(engines)}); "
            "Serein will not install a competing engine (see S3 ADR-0011, "
            "not reopened here).", False, True, "none",
            "podman --version || docker --version", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action, "podman", "ubuntu-repository", "not installed", "podman",
        "S3's Podman-default policy is not reopened for S4; GPU passthrough "
        "uses CDI, which works with Podman too.", True, True, "low",
        "podman --version", "APPLY",
    )


def _nvidia_container_toolkit_action(
    containers: AIContainerStatusInfo, backend: AIBackendInfo, environment_is_container: bool
) -> AIPlanAction:
    action_id, component, action = "containers.nvidia_toolkit", "containers", "install_apt_packages"
    nvidia_backend = any(c.backend == "nvidia_cuda" for c in backend.candidates)
    if environment_is_container or not nvidia_backend:
        reason = (
            "Running inside a container." if environment_is_container
            else "No NVIDIA backend candidate detected."
        )
        return AIPlanAction(
            action_id, component, action, "nvidia-container-toolkit",
            "official-upstream-repository", "not applicable", None, reason,
            False, True, "none", "n/a", "SKIP",
        )
    if containers.nvidia_container_toolkit.installed:
        return AIPlanAction(
            action_id, component, action, "nvidia-container-toolkit",
            "official-upstream-repository", "installed", "installed",
            "NVIDIA Container Toolkit is already installed.", False, True,
            "none", "nvidia-ctk --version", "NOOP",
        )
    return AIPlanAction(
        action_id, component, action, "nvidia-container-toolkit",
        "official-upstream-repository", "not installed", "current",
        "NVIDIA's own apt repository. Current mechanism is CDI-based "
        "(`nvidia-ctk cdi generate`), works with both Docker and Podman.",
        True, True, "low", "nvidia-ctk --version", "APPLY",
    )


def _voice_action() -> AIPlanAction:
    return AIPlanAction(
        "voice.workload_note", "voice", "report_only", "ffmpeg + PyTorch + audio libs",
        "ubuntu-repository", None, None,
        "The voice/RVC workload class needs ffmpeg (base apt package) plus a "
        "PyTorch environment; specific audio-processing libraries are "
        "project-specific and not part of Serein's default manifest. Serein "
        "never installs model files and never inspects voice datasets - see "
        "docs/ai/known-limitations.md.", False, True, "none", "n/a", "NOOP",
    )


def build_ai_plan(
    component: str | None = None,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
) -> AIPlan:
    if component is not None and component not in VALID_COMPONENTS:
        raise ValueError(f"unknown AI plan component: {component!r}")

    gpus = detect_gpus(root)
    gpu_policy = detect_gpu_policy(root, gpus)
    backend = classify_backend(gpus, gpu_policy)

    nvidia = detect_nvidia_status(gpu_policy, runner=runner, root=root)
    amd = detect_amd_status(gpu_policy, runner=runner)
    pytorch = detect_pytorch_status(runner=runner)
    py_packages = detect_python_ai_packages(runner=runner)
    inference = detect_inference_status(runner=runner)
    containers = detect_ai_container_status(runner=runner, root=root)

    environment_is_container = detect_environment(root).is_container

    actions = [
        _driver_action(nvidia, backend),
        _cuda_toolkit_action(nvidia),
        _rocm_action(amd),
        _pytorch_action(pytorch, backend),
        _transformers_action(py_packages),
        _ollama_action(inference),
        _llama_cpp_action(inference),
        _containers_action(containers, backend, environment_is_container),
        _nvidia_container_toolkit_action(containers, backend, environment_is_container),
        _voice_action(),
    ]

    if component is not None:
        actions = [a for a in actions if a.component == component]

    return AIPlan(schema_version=AI_PLAN_SCHEMA_VERSION, actions=actions)
