"""Structured representations for the AI workstation subsystem.

Mirrors the pattern S2 (``hardware/models.py``) and S3
(``development/models.py``) established — dataclasses only, no
behavior, no runtime dependency on any AI library. See
``docs/ai/architecture.md``.

S4 deliberately reuses S3's ``ToolDefinition``/``ToolStatus`` and risk
model rather than forking a second, incompatible taxonomy (Section 86
of the S4 brief) — see ``serein.development.models`` for those. This
module adds only what is genuinely new for AI: backend classification,
NVIDIA/AMD/Intel-specific status shapes, and AI-specific capability/plan
report wrappers (kept structurally identical to S3's so the CLI/schema
layer stays consistent, but versioned independently since they are a
distinct machine-readable surface).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from serein.development.models import ToolStatus

AI_CAPABILITIES_SCHEMA_VERSION = 1
AI_PLAN_SCHEMA_VERSION = 1

#: Independent of ``serein.__version__`` and of S3's
#: ``DEVELOPMENT_CONFIG_VERSION`` — bumped only if S4 ever ships a
#: managed config resource (none does yet; see docs/ai/architecture.md).
AI_CONFIG_VERSION = 1

#: Recognized AI workload intents (Section 53) — informational tags
#: used by focused plans and documentation, never a second profile
#: system. Deliberately small; do not add a profile per model/tool.
AI_WORKLOAD_INTENTS: tuple[str, ...] = (
    "inference", "development", "training", "voice", "cpu-inference",
)

#: Hardware backend classes a workload could target (Section 5).
#: "unknown" means GPU hardware exists but its vendor/capability could
#: not be confidently classified — never silently treated as "cpu".
AI_BACKEND_CLASSES: tuple[str, ...] = (
    "nvidia_cuda", "amd_rocm", "intel_gpu", "cpu", "unknown",
)

#: Extends `serein.development.models.ToolSourceType` (still a plain
#: string, not a fork of that taxonomy) with one new, justified value:
#: a package installed via `uv` from PyPI/a framework's own wheel index
#: (torch, transformers, vllm, ...) into the Serein-managed AI
#: environment — never system Python, never apt. See
#: docs/ai/architecture.md.
AI_PYTHON_PACKAGE_SOURCE = "python-package-index"


@dataclass(frozen=True)
class AIBackendCandidate:
    """One GPU device's AI-backend relevance — enriches S2's
    ``GPUDevice``/``GPUClassification`` with AI-runtime meaning, never
    re-probing hardware itself (S4 brief Section 5)."""

    backend: str  # one of AI_BACKEND_CLASSES
    vendor: str | None
    kind: str  # "integrated" | "discrete" | "unknown", from S2
    confidence: str  # "high" | "medium" | "low"


@dataclass
class AIBackendInfo:
    """The recommended AI compute backend for this machine and why —
    distinct from "is that backend's runtime actually usable", which
    is nvidia.py/amd.py/intel.py's job (Section 6: hardware presence
    != backend usable)."""

    primary: str  # one of AI_BACKEND_CLASSES
    primary_confidence: str  # "high" | "medium" | "low"
    candidates: list[AIBackendCandidate] = field(default_factory=list)
    hybrid: bool | None = False  # from GPUPolicyInfo.hybrid, unchanged
    reason: str = ""


#: Coarse VRAM tiers (Section 30) — influence recommendations only,
#: never hard-block AI capability. Ceilings in MiB; the label is the
#: upper-open interval, e.g. "6-8GiB" means [6144, 8192) MiB.
_VRAM_TIER_CEILINGS: tuple[tuple[int, str], ...] = (
    (6 * 1024, "<6GiB"),
    (8 * 1024, "6-8GiB"),
    (12 * 1024, "8-12GiB"),
    (24 * 1024, "12-24GiB"),
)


def classify_vram_tier(total_mib: int) -> str:
    for ceiling, label in _VRAM_TIER_CEILINGS:
        if total_mib < ceiling:
            return label
    return "24GiB+"


@dataclass(frozen=True)
class VRAMInfo:
    """Per-device VRAM — populated only from real evidence
    (nvidia-smi's own memory.total query for NVIDIA; AMD/Intel report
    ``total_mib=None`` unless a verified-semantics source exists, per
    Section 52 — never guessed from a GPU model name)."""

    total_mib: int | None = None
    tier: str | None = None


@dataclass
class NvidiaStatus:
    hardware_present: bool = False
    kernel_module_loaded: bool = False
    nvidia_smi: ToolStatus = field(default_factory=lambda: ToolStatus(id="nvidia-smi"))
    driver_version: str | None = None
    #: The CUDA *driver API* version nvidia-smi reports (top-right
    #: field) — NEVER treated as proof a CUDA Toolkit is installed
    #: (S4 brief Section 16). Kept in a separate field from
    #: cuda_toolkit_installed specifically so the two can never be
    #: conflated by a caller reading this struct.
    cuda_driver_api_version: str | None = None
    nvcc: ToolStatus = field(default_factory=lambda: ToolStatus(id="nvcc"))
    #: True only from STRONG evidence: `nvcc --version` succeeding, or
    #: dpkg reporting the `cuda-toolkit` package genuinely installed
    #: (S4R Section 17/18 — a real regression fixed here: a bare
    #: `/usr/local/cuda*` directory/symlink existing is NOT, by itself,
    #: sufficient — an empty or stale marker previously produced a
    #: false positive). See `cuda_toolkit_marker_present` for that
    #: weaker, auxiliary-only signal.
    cuda_toolkit_installed: bool = False
    #: A `/usr/local/cuda` marker (symlink or directory) exists —
    #: existence only, contents never read. Auxiliary evidence only:
    #: never sufficient on its own to set `cuda_toolkit_installed`.
    #: True with `cuda_toolkit_installed=False` is itself a real,
    #: doctor-worthy signal (a stale/incomplete install).
    cuda_toolkit_marker_present: bool = False
    #: Real versioned `/usr/local/cuda-*` directory names found
    #: (existence/listing only, never contents) — more than one is a
    #: real "multiple toolkit indicators" signal for the doctor, not a
    #: resolved "which one is active" claim.
    cuda_toolkit_dirs: list[str] = field(default_factory=list)
    nvidia_ctk: ToolStatus = field(default_factory=lambda: ToolStatus(id="nvidia-ctk"))
    #: Per-GPU VRAM, queried only when the driver is usable (a
    #: `nvidia-smi` call) — empty when the driver can't be queried.
    vram: list[VRAMInfo] = field(default_factory=list)


@dataclass
class RocmSupportInfo:
    """Distinguishes three different questions Serein must never
    conflate (S4R Section 11/12): whether ROCm's own runtime tooling is
    installed at all, whether that runtime enumerates a GPU agent (real
    local evidence ROCm/HSA recognizes this hardware), and whether
    PyTorch's own ROCm-wheel/MIOpen/framework-level compatibility is
    established for this exact combination — the last of which this
    struct deliberately does NOT claim to answer (see pytorch.py's
    ``select_pytorch_backend``, which treats framework compatibility as
    a separate, always-conservative question even when
    ``gpu_enumerated`` is True)."""

    runtime_installed: bool = False
    #: True only when `rocminfo` actually enumerates a `Device Type:
    #: GPU` agent; False when it runs but reports none; None when the
    #: runtime isn't installed (nothing to query). This proves ROCm's
    #: own runtime recognizes the hardware — it does NOT by itself
    #: prove PyTorch/MIOpen/framework-level compatibility.
    gpu_enumerated: bool | None = None
    confidence: str = "low"  # "high" | "medium" | "low"
    reason: str = "No ROCm runtime installed to query."


@dataclass
class AmdStatus:
    hardware_present: bool = False
    kernel_module_loaded: bool = False
    rocminfo: ToolStatus = field(default_factory=lambda: ToolStatus(id="rocminfo"))
    rocm_smi: ToolStatus = field(default_factory=lambda: ToolStatus(id="rocm-smi"))
    rocm_support: RocmSupportInfo = field(default_factory=RocmSupportInfo)


@dataclass
class IntelAIStatus:
    hardware_present: bool = False
    kind: str | None = None  # "integrated" | "discrete" | "unknown", from S2
    #: PyTorch's native XPU backend compatibility for this specific
    #: hardware. Always "unknown" as of this pass — Serein has no
    #: live-verified evidence either way and will not claim
    #: "supported" without it (S4R Section 34; see
    #: docs/ai/intel-strategy.md). "unsupported" is reserved for a
    #: future pass that gains real negative evidence.
    xpu_compatibility: str = "unknown"  # "unknown" | "unsupported"


@dataclass(frozen=True)
class PyTorchBackendDecision:
    """The single shared computation of "what PyTorch backend should
    be planned" — consumed identically by planner.py and
    capabilities.py so the two can never derive incompatible
    conclusions (S4R Section 9, the S2RM/S3R lesson applied here before
    an S4-native version of that defect could ship). See
    ``pytorch.select_pytorch_backend``.

    ``status="APPLY"`` means ``target`` is immediately actionable
    (either a proven-ready accelerator build, or the always-ready CPU
    fallback). ``status="BLOCKED"`` means an accelerator hardware
    candidate exists but its runtime/framework-compatibility could not
    be confirmed — Serein deliberately does not silently substitute a
    CPU build in that case (S4R Section 5); it also does not install a
    second, unproven accelerator build. Other AI actions (Ollama,
    llama.cpp) remain independently plannable regardless — this never
    blocks the whole AI profile, only the PyTorch-specific action."""

    target: str  # "cpu" | "cuda" | "rocm" | "xpu"
    status: str  # "APPLY" | "BLOCKED"
    confidence: str  # "high" | "medium" | "low"
    reason: str


@dataclass
class PyTorchStatus:
    """Detected via a bounded, injectable subprocess probe against
    whatever ``python3`` resolves to on PATH — never an in-process
    ``import torch`` inside Serein's own control plane (S4 brief
    Section 60/61). ``torch.cuda.is_available()`` is deliberately never
    called (it can initialize/touch the GPU and hang on a broken
    driver) — only the static build-variant fields the import exposes
    are read."""

    installed: ToolStatus = field(default_factory=lambda: ToolStatus(id="torch"))
    #: "cuda" | "rocm" | "cpu" | None (not installed / undetermined)
    build_backend: str | None = None
    build_backend_version: str | None = None


@dataclass
class PythonAIPackagesStatus:
    """Presence of the Transformers baseline + optional packages,
    each detected via ``importlib.metadata`` in a subprocess (never an
    actual import of the package) — see python_env.py."""

    transformers: ToolStatus = field(default_factory=lambda: ToolStatus(id="transformers"))
    accelerate: ToolStatus = field(default_factory=lambda: ToolStatus(id="accelerate"))
    safetensors: ToolStatus = field(default_factory=lambda: ToolStatus(id="safetensors"))
    huggingface_hub: ToolStatus = field(default_factory=lambda: ToolStatus(id="huggingface_hub"))
    vllm: ToolStatus = field(default_factory=lambda: ToolStatus(id="vllm"))
    onnxruntime: ToolStatus = field(default_factory=lambda: ToolStatus(id="onnxruntime"))
    tensorrt: ToolStatus = field(default_factory=lambda: ToolStatus(id="tensorrt"))
    bitsandbytes: ToolStatus = field(default_factory=lambda: ToolStatus(id="bitsandbytes"))


@dataclass
class OllamaStatus:
    binary: ToolStatus = field(default_factory=lambda: ToolStatus(id="ollama"))
    #: True/False only from a real, read-only "is this unit active"
    #: query (`systemctl is-active`) — never started/stopped by
    #: Serein. None if systemctl/the unit isn't queryable at all.
    service_active: bool | None = None


@dataclass
class LlamaCppStatus:
    #: Current canonical binaries (renamed from `main`/`server` -
    #: see docs/ai/inference-strategy.md); both probed independently
    #: since a source build may produce one without the other.
    llama_cli: ToolStatus = field(default_factory=lambda: ToolStatus(id="llama-cli"))
    llama_server: ToolStatus = field(default_factory=lambda: ToolStatus(id="llama-server"))


@dataclass
class InferenceStatus:
    ollama: OllamaStatus = field(default_factory=OllamaStatus)
    llama_cpp: LlamaCppStatus = field(default_factory=LlamaCppStatus)


@dataclass
class AIContainerStatusInfo:
    """Reuses S3's container detection for podman/docker/distrobox
    (Section 86 - never re-probed independently) and adds the
    NVIDIA-specific GPU-container layer on top."""

    podman: ToolStatus = field(default_factory=lambda: ToolStatus(id="podman"))
    docker: ToolStatus = field(default_factory=lambda: ToolStatus(id="docker"))
    distrobox: ToolStatus = field(default_factory=lambda: ToolStatus(id="distrobox"))
    nvidia_container_toolkit: ToolStatus = field(
        default_factory=lambda: ToolStatus(id="nvidia-container-toolkit")
    )
    #: Whether NVIDIA CDI integration for containers is evidenced —
    #: either a real spec file (`/etc/cdi/nvidia.yaml` or
    #: `/var/run/cdi/nvidia.yaml`, existence only, contents never read)
    #: or a successful, read-only `nvidia-ctk cdi list` reporting a
    #: real device entry (current NVIDIA Container Toolkit releases can
    #: generate/manage CDI specs automatically, so a static file is not
    #: the only valid evidence — S4R Section 27/28). Never generated,
    #: listed, or mutated by Serein beyond this read-only check.
    cdi_nvidia_generated: bool = False


@dataclass
class AIStorageInfo:
    """Logical, configurable roots only (S4 brief Section 45/46) - S4
    never assumes a dedicated data volume exists. Every path field is
    pre-normalized to a ``~``-relative or env-var-name form before
    being stored here, never a raw absolute path containing the real
    username (see docs/ai/storage-strategy.md and the privacy tests)."""

    #: Hugging Face cache location: the current value of $HF_HOME if
    #: set (normalized), else the documented default
    #: ("~/.cache/huggingface").
    hf_home: str = "~/.cache/huggingface"
    hf_home_is_default: bool = True
    #: Ollama's model storage: $OLLAMA_MODELS if set, else Ollama's
    #: own documented default ("~/.ollama/models").
    ollama_models: str = "~/.ollama/models"
    ollama_models_is_default: bool = True
    #: Free space at whichever of the above paths' nearest existing
    #: ancestor directory, if safely determinable - None if not.
    cache_free_bytes: int | None = None
    low_space_warning: bool = False


@dataclass
class AICapability:
    """Mirrors ``serein.development.models.DevelopmentCapability``'s
    shape exactly (Section 87) plus one AI-specific field: ``usable``,
    distinct from ``installed`` (S4 brief Section 7 - hardware/runtime
    presence is not the same question as "would actually work")."""

    id: str
    available: bool | None  # can Serein plan this at all here
    installed: bool
    usable: bool | None  # None = unknown/unverified, never guessed True
    mechanism: str | None
    source: str | None
    confidence: str  # "high" | "medium" | "low"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AICapabilitiesReport:
    schema_version: int
    capabilities: list[AICapability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass
class AIPlanAction:
    """Identical shape to ``serein.development.models.DevPlanAction``
    (Section 11/86) - deliberately not reused directly since the two
    are separate machine-readable surfaces with independent schema
    versions, but kept structurally identical so the CLI rendering
    code and mental model transfer without translation."""

    id: str
    component: str
    action: str
    tool: str
    source: str | None
    current: str | None
    target: str | None
    reason: str
    requires_root: bool
    reversible: bool
    risk: str  # "none" | "low" | "medium" | "high"
    verification: str
    status: str  # "APPLY" | "NOOP" | "SKIP" | "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AIPlan:
    schema_version: int
    actions: list[AIPlanAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class AIStatusReport:
    schema_version: int
    profile_id: str
    profile_status: str
    backend: AIBackendInfo
    nvidia: NvidiaStatus
    amd: AmdStatus
    intel: IntelAIStatus
    pytorch: PyTorchStatus
    pytorch_decision: PyTorchBackendDecision
    python_packages: PythonAIPackagesStatus
    inference: InferenceStatus
    containers: AIContainerStatusInfo
    storage: AIStorageInfo

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
