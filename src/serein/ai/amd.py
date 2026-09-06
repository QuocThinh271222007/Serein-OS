"""AMD GPU / ROCm detection.

ROCm support is architecture-specific and Serein does not maintain a
GPU-model-to-support mapping table (S4 brief Section 35/91 — such a
table goes stale immediately and PCI device IDs alone are not a
trustworthy signal). Instead, ``rocm_support`` distinguishes three
different questions (S4R Section 11/12 — the original ``supported``
boolean overstated its own evidence by collapsing them into one):

1. **Is the ROCm runtime installed at all** (``runtime_installed`` —
   the ``rocminfo`` binary exists)?
2. **Does that runtime enumerate a GPU agent** (``gpu_enumerated`` —
   ``rocminfo``'s own output reports a ``Device Type: GPU`` entry)?
   This is real, local evidence that ROCm/HSA recognizes the hardware.
3. **Is PyTorch's own ROCm-wheel/MIOpen/framework-level compatibility
   established** for this exact GPU/framework combination? This
   module does **not** answer that question — ``gpu_enumerated=True``
   is real hardware-runtime evidence, but it is explicitly NOT treated
   as proof of framework-level compatibility (see
   ``pytorch.select_pytorch_backend``, which keeps this a separate,
   always-conservative gate even when ROCm enumerates the GPU).

This never guesses from a vendor ID or model name.
"""

from __future__ import annotations

import re

from serein.ai.models import AmdStatus, RocmSupportInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware.models import GPUPolicyInfo

_GPU_AGENT_RE = re.compile(r"Device Type:\s*GPU", re.IGNORECASE)


def _detect_rocm_support(rocminfo_installed: bool, runner: CommandRunner) -> RocmSupportInfo:
    if not rocminfo_installed:
        return RocmSupportInfo(
            runtime_installed=False,
            gpu_enumerated=None,
            confidence="low",
            reason=(
                "No ROCm runtime (rocminfo) installed to query; AMD hardware "
                "presence alone does not establish ROCm support - see "
                "docs/ai/amd-rocm-strategy.md."
            ),
        )
    result = runner.run(["rocminfo"], timeout=5.0)
    if result is None or result.returncode != 0:
        return RocmSupportInfo(
            runtime_installed=True,
            gpu_enumerated=None,
            confidence="low",
            reason="rocminfo is installed but did not run successfully; support unknown.",
        )
    if _GPU_AGENT_RE.search(result.stdout):
        return RocmSupportInfo(
            runtime_installed=True,
            gpu_enumerated=True,
            confidence="high",
            reason="rocminfo enumerates at least one GPU agent. This confirms "
            "ROCm's own runtime recognizes the hardware - it does not by "
            "itself prove PyTorch/MIOpen/framework-level compatibility.",
        )
    return RocmSupportInfo(
        runtime_installed=True,
        gpu_enumerated=False,
        confidence="high",
        reason="rocminfo ran but reported no GPU agent; ROCm does not support this hardware.",
    )


def detect_amd_status(
    gpu_policy: GPUPolicyInfo, runner: CommandRunner = DEFAULT_RUNNER
) -> AmdStatus:
    rocminfo = probe_tool("rocminfo", "rocminfo", runner=runner)
    rocm_smi = probe_tool("rocm-smi", "rocm-smi", runner=runner)
    amd_present = any(c.vendor == "AMD" for c in gpu_policy.classifications)

    return AmdStatus(
        hardware_present=amd_present,
        kernel_module_loaded=gpu_policy.amdgpu_kernel_module_loaded,
        rocminfo=rocminfo,
        rocm_smi=rocm_smi,
        rocm_support=_detect_rocm_support(rocminfo.installed, runner),
    )
