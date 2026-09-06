"""Serein AI's declarative tool/source manifest.

Reuses ``serein.development.models.ToolDefinition`` directly (Section
86 — no second, incompatible taxonomy) and its existing
``source_type`` values, plus one new, documented addition:
``AI_PYTHON_PACKAGE_SOURCE`` ("python-package-index") for packages
installed via ``uv`` from PyPI/a framework's own wheel index — never
apt, never system Python. This module is plain data: nothing here
executes a package manager, an installer script, or a driver
installer. See docs/ai/package-strategy.md (folded into
architecture.md - a standalone doc was not warranted for this small a
manifest).

Every non-APT source's exact mechanism is deliberately generic rather
than a specific version number (Section 17: "represent compatibility,
not chase the newest number") — a driver/CUDA/ROCm/PyTorch version is
resolved at a future Apply stage against then-current compatibility
evidence, never hardcoded here.
"""

from __future__ import annotations

from serein.ai.models import AI_PYTHON_PACKAGE_SOURCE
from serein.development.models import ToolDefinition

# --- Base --------------------------------------------------------------

BASE_AI_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "ffmpeg", "ffmpeg", "ubuntu-repository", "ffmpeg", True,
        "Audio/video codec toolkit - useful for AI data preprocessing and "
        "the voice/RVC workload class. A normal, current Ubuntu archive "
        "package (verified - see docs/validation/s4/ubuntu-package-validation.md).",
    ),
)

# --- NVIDIA --------------------------------------------------------------

NVIDIA_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "nvidia-driver", "NVIDIA Driver (Ubuntu-recommended)", "ubuntu-repository", None, True,
        "Installed via `ubuntu-drivers autoinstall`/Ubuntu's own recommended "
        "package - Serein does not hardcode a specific driver version (the "
        "correct one is host- and Secure-Boot-state-dependent; DKMS/kernel "
        "lifecycle is Ubuntu's job). NVIDIA's own .run installer is "
        "explicitly discouraged - see docs/ai/nvidia-strategy.md.",
    ),
    ToolDefinition(
        "cuda-toolkit", "CUDA Toolkit", "ubuntu-repository", "cuda-toolkit", True,
        "Ubuntu 26.04 packages CUDA Toolkit directly in its own multiverse "
        "archive (verified live: `cuda-toolkit` -> 13.1.1-0ubuntu1, from "
        "archive.ubuntu.com/ubuntu resolute/multiverse - see "
        "docs/validation/s4/ubuntu-package-validation.md), a genuine "
        "packaging change from older Ubuntu LTS releases that required "
        "NVIDIA's own apt repository. Exact version chosen for driver/"
        "PyTorch/Ubuntu compatibility, not 'latest' - see "
        "docs/ai/nvidia-strategy.md.",
    ),
    ToolDefinition(
        "nvidia-container-toolkit", "NVIDIA Container Toolkit",
        "official-upstream-repository", None, True,
        "NVIDIA's own apt repository. Current mechanism is CDI-based "
        "(`nvidia-ctk cdi generate`), superseding the older nvidia-docker2 "
        "runtime approach, and works with both Docker and Podman - see "
        "docs/ai/container-strategy.md.",
    ),
)

# --- AMD -----------------------------------------------------------------

AMD_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "rocm", "ROCm", "ubuntu-repository", "rocm", True,
        "Ubuntu 26.04 packages ROCm directly in its own universe archive "
        "(verified live: `rocm` -> 7.1.0-0ubuntu6, `rocminfo` -> "
        "7.1.1-0ubuntu1, `rocm-smi` -> 7.1.1-0ubuntu1, all from "
        "archive.ubuntu.com/ubuntu resolute/universe - see "
        "docs/validation/s4/ubuntu-package-validation.md), a genuine "
        "packaging change from AMD's own amdgpu-install-based mechanism "
        "required on older Ubuntu LTS releases. Only planned when real "
        "runtime evidence (rocminfo) confirms support - see "
        "docs/ai/amd-rocm-strategy.md.",
    ),
)

# --- Intel -----------------------------------------------------------------

INTEL_TOOLS_OPTIONAL: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "intel-extension-for-pytorch", "Intel Extension for PyTorch",
        AI_PYTHON_PACKAGE_SOURCE, "intel-extension-for-pytorch", False,
        "Optional: Intel's own PyPI package extending PyTorch with XPU "
        "support. Maturity not currently verified end-to-end by Serein - "
        "see docs/ai/intel-strategy.md. Not part of the default plan.",
    ),
)

# --- Python AI environment (Transformers baseline) ------------------------

PYTHON_AI_BASE_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "transformers", "Transformers", AI_PYTHON_PACKAGE_SOURCE, "transformers", False,
        "Hugging Face's model/tokenizer library - installed via `uv` into a "
        "project environment, never system Python.",
    ),
    ToolDefinition(
        "accelerate", "Accelerate", AI_PYTHON_PACKAGE_SOURCE, "accelerate", False,
        "Hugging Face's device/precision-placement helper.",
    ),
    ToolDefinition(
        "safetensors", "safetensors", AI_PYTHON_PACKAGE_SOURCE, "safetensors", False,
        "Safe (non-pickle) tensor serialization format - preferred over "
        "pickle-based .pth where a model provides it.",
    ),
    ToolDefinition(
        "huggingface_hub", "huggingface_hub", AI_PYTHON_PACKAGE_SOURCE, "huggingface_hub", False,
        "Model/dataset download and cache client.",
    ),
)

PYTHON_AI_OPTIONAL_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "bitsandbytes", "bitsandbytes", AI_PYTHON_PACKAGE_SOURCE, "bitsandbytes", False,
        "Optional: quantization/8-bit optimizer support. Platform/CUDA/GPU "
        "compatibility varies significantly - never a default dependency.",
    ),
    ToolDefinition(
        "flash-attn", "Flash Attention", AI_PYTHON_PACKAGE_SOURCE, "flash-attn", False,
        "Optional: fused attention kernels. Hardware/compiler/backend "
        "constraints make it unsuitable as a universal baseline.",
    ),
    ToolDefinition(
        "datasets", "Hugging Face Datasets", AI_PYTHON_PACKAGE_SOURCE, "datasets", False,
        "Optional: dataset loading/processing - workload-specific, not "
        "every AI use case needs it.",
    ),
    ToolDefinition(
        "peft", "PEFT", AI_PYTHON_PACKAGE_SOURCE, "peft", False,
        "Optional: parameter-efficient fine-tuning (LoRA etc.) - training "
        "workload-specific.",
    ),
    ToolDefinition(
        "trl", "TRL", AI_PYTHON_PACKAGE_SOURCE, "trl", False,
        "Optional: RLHF/fine-tuning trainer library - training "
        "workload-specific.",
    ),
)

# --- PyTorch ---------------------------------------------------------------

PYTORCH_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "torch", "PyTorch", AI_PYTHON_PACKAGE_SOURCE, "torch", False,
        "Installed via `uv` from PyTorch's own per-backend index URL "
        "(download.pytorch.org/whl/<cuXXX|rocmX.Y|cpu>), never plain PyPI "
        "for a GPU build and never into system Python. Exactly one backend "
        "variant is planned, chosen from the classified AI backend - see "
        "docs/ai/pytorch-strategy.md and ADR-0014.",
    ),
)

# --- Inference runtimes ------------------------------------------------

INFERENCE_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "ollama", "Ollama", "official-upstream-binary", None, False,
        "Official installer script (ollama.com/install.sh) - user-level, "
        "no Ubuntu package/apt repo currently exists. Not executed by S4 - "
        "see docs/ai/inference-strategy.md.",
    ),
    ToolDefinition(
        "llama.cpp", "llama.cpp", "official-upstream-binary", None, False,
        "No official Ubuntu package - built from source or a GitHub "
        "Releases prebuilt asset (upstream provides both). Documented, "
        "never executed by S4 - see docs/ai/inference-strategy.md.",
    ),
)

INFERENCE_OPTIONAL_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "vllm", "vLLM", AI_PYTHON_PACKAGE_SOURCE, "vllm", False,
        "Optional: high-throughput inference/serving. Primarily a CUDA+Linux "
        "workload; not every workstation needs it - see "
        "docs/ai/inference-strategy.md.",
    ),
    ToolDefinition(
        "onnxruntime", "ONNX Runtime", AI_PYTHON_PACKAGE_SOURCE, "onnxruntime", False,
        "Optional: portable, cross-vendor inference. `onnxruntime-gpu` is a "
        "separate, NVIDIA-specific package variant, also optional.",
    ),
    ToolDefinition(
        "tensorrt", "TensorRT", AI_PYTHON_PACKAGE_SOURCE, "tensorrt", False,
        "Optional, NVIDIA-specific: only ever planned when compatible with "
        "the already-detected CUDA/driver stack - never a base dependency.",
    ),
)

ALL_GROUPS: tuple[tuple[str, tuple[ToolDefinition, ...]], ...] = (
    ("base", BASE_AI_TOOLS),
    ("nvidia", NVIDIA_TOOLS),
    ("amd", AMD_TOOLS),
    ("intel-optional", INTEL_TOOLS_OPTIONAL),
    ("python-ai", PYTHON_AI_BASE_TOOLS),
    ("python-ai-optional", PYTHON_AI_OPTIONAL_TOOLS),
    ("pytorch", PYTORCH_TOOLS),
    ("inference", INFERENCE_TOOLS),
    ("inference-optional", INFERENCE_OPTIONAL_TOOLS),
)


def all_tools() -> list[ToolDefinition]:
    """Every declared AI tool across every group, default and optional
    alike - deduplicated by id."""
    seen: set[str] = set()
    result: list[ToolDefinition] = []
    for _group_name, tools in ALL_GROUPS:
        for tool in tools:
            if tool.id not in seen:
                seen.add(tool.id)
                result.append(tool)
    return result
