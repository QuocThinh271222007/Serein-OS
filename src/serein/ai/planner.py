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
from serein.ai.intel import detect_intel_status
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
    PyTorchBackendDecision,
    PyTorchStatus,
)
from serein.ai.nvidia import detect_nvidia_status
from serein.ai.python_env import detect_python_ai_packages
from serein.ai.pytorch import detect_pytorch_status, select_pytorch_backend
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
    """The CUDA Toolkit (nvcc, native compilation) is NOT a default
    prerequisite for ordinary PyTorch/inference use - prebuilt PyTorch
    CUDA wheels bundle their own required CUDA userspace runtime
    libraries (S4R Section 21/22/23). This action is therefore never
    APPLY: it is SKIP when there is nothing to detect it against, NOOP
    when already installed, and NOOP-as-optional otherwise, explaining
    how to install it manually for native-CUDA-development workloads
    (nvcc, source builds, custom CUDA extensions) that do need it."""
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
            "A CUDA Toolkit installation was already detected (nvcc or "
            "dpkg package state).", False, True, "none", "nvcc --version", "NOOP",
        )
    marker_note = (
        " A /usr/local/cuda marker exists but is not, by itself, proof of "
        "installation (it may be stale/incomplete) - see nvidia.py."
        if nvidia.cuda_toolkit_marker_present else ""
    )
    return AIPlanAction(
        action_id, component, action, "cuda-toolkit", "ubuntu-repository",
        "not installed (optional)", None,
        "Not part of Serein's default plan: prebuilt PyTorch CUDA wheels "
        "bundle their own required CUDA userspace runtime libraries, so a "
        "local CUDA Toolkit is not required for ordinary PyTorch/inference "
        "workloads. Only needed for native CUDA development, nvcc, source "
        "builds, or custom CUDA extensions - install manually "
        "(`sudo apt install cuda-toolkit`, Ubuntu's own multiverse archive, "
        "verified live) once a working driver is confirmed if your workload "
        "needs it. See docs/ai/nvidia-strategy.md." + marker_note,
        False, True, "none", "nvcc --version", "NOOP",
    )


def _pytorch_action(pytorch: PyTorchStatus, decision: PyTorchBackendDecision) -> AIPlanAction:
    """PyTorch backend selection is runtime-gated via
    ``select_pytorch_backend`` (S4R Section 4/9) - never derived from
    the hardware candidate alone. When the accelerator path is
    ``BLOCKED`` (unresolved runtime/framework compatibility), this
    action stays BLOCKED rather than silently substituting a CPU
    build - other AI actions (Ollama, llama.cpp) remain independently
    plannable, so this never blocks the whole AI profile."""
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
    if decision.status == "BLOCKED":
        return AIPlanAction(
            action_id, component, action, "torch", "python-package-index",
            "not installed", f"{decision.target} build (blocked)",
            decision.reason, False, True, "low", "n/a", "BLOCKED",
        )
    return AIPlanAction(
        action_id, component, action, "torch", "python-package-index",
        "not installed", f"{decision.target} build",
        f"Installed via `uv` from PyTorch's own {decision.target} index/wheel, "
        "into a project/AI environment - never system Python, never "
        f"`sudo pip install torch`. {decision.reason} See "
        "docs/ai/pytorch-strategy.md and ADR-0014.",
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
    """ROCm GPU enumeration (``amd.rocm_support.gpu_enumerated``) can
    only ever be confirmed True/False by ROCm's own tooling
    (``rocminfo``) actually running - which means it is only ever
    non-``None`` when ``rocminfo`` is already installed. So there are
    really only two reachable states once AMD hardware is present:
    rocminfo already installed (NOOP - regardless of what it reports;
    an installed-but-unsupported combination is the doctor's
    ``ai_rocm_unsupported_hardware`` WARN to surface, not something
    reinstalling ROCm would fix), or rocminfo absent, in which case
    enumeration is unconditionally unknown and Serein will not guess
    from vendor ID alone (BLOCKED). This action only covers the ROCm
    *runtime* itself - whether PyTorch should target it is a separate
    question, see ``select_pytorch_backend``."""
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
    """The official Ollama Linux installer is SYSTEM-level, not
    user-level (S4R Section 36/37/38): it places the binary under
    /usr/local/bin (root-owned), creates a system `ollama` user/group,
    and registers a systemd service - all requiring root. This must
    never be represented as a quiet, low-risk, user-level install."""
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
        "Official installer: ollama.com/install.sh (not executed by S4; a "
        "future Apply must download/verify the artifact rather than pipe "
        "curl straight to sh - see docs/ai/security.md). This is a "
        "system-level install: it places the binary under /usr/local/bin, "
        "creates a system `ollama` user/group, and registers a systemd "
        "service. Reversible, but multi-step (remove the service, binary, "
        "and system user) - not a plain file deletion. Convenient model "
        "lifecycle/server UX; coexists with llama.cpp.",
        True, True, "medium", "ollama --version", "APPLY",
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
    containers: AIContainerStatusInfo,
    backend: AIBackendInfo,
    nvidia: NvidiaStatus,
    environment_is_container: bool,
) -> AIPlanAction:
    """Do not plan NVIDIA Container Toolkit merely because an NVIDIA
    backend candidate exists if the driver path is unresolved (S4R
    Section 30) - a working driver is a prerequisite for the toolkit
    to be usable at all, so provisioning it first would be premature."""
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
    if nvidia.driver_version is None:
        return AIPlanAction(
            action_id, component, action, "nvidia-container-toolkit",
            "official-upstream-repository", "driver missing", None,
            "An NVIDIA backend candidate exists, but a working NVIDIA "
            "driver must be proven first - the toolkit would not be "
            "usable without it. See nvidia.driver.", False, True, "none",
            "n/a", "BLOCKED",
        )
    return AIPlanAction(
        action_id, component, action, "nvidia-container-toolkit",
        "official-upstream-repository", "not installed", "current",
        "NVIDIA's own apt repository. Current mechanism is CDI-based; "
        "current NVIDIA Container Toolkit releases can generate/manage CDI "
        "specs automatically (nvidia-ctk cdi generate is not always a "
        "required manual step) and work with both Docker and Podman.",
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
    intel = detect_intel_status(gpu_policy)
    pytorch = detect_pytorch_status(runner=runner)
    py_packages = detect_python_ai_packages(runner=runner)
    inference = detect_inference_status(runner=runner)
    containers = detect_ai_container_status(runner=runner, root=root)

    environment_is_container = detect_environment(root).is_container
    pytorch_decision = select_pytorch_backend(backend, nvidia, amd, intel)

    actions = [
        _driver_action(nvidia, backend),
        _cuda_toolkit_action(nvidia),
        _rocm_action(amd),
        _pytorch_action(pytorch, pytorch_decision),
        _transformers_action(py_packages),
        _ollama_action(inference),
        _llama_cpp_action(inference),
        _containers_action(containers, backend, environment_is_container),
        _nvidia_container_toolkit_action(containers, backend, nvidia, environment_is_container),
        _voice_action(),
    ]

    if component is not None:
        actions = [a for a in actions if a.component == component]

    return AIPlan(schema_version=AI_PLAN_SCHEMA_VERSION, actions=actions)
