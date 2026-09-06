"""AMD GPU / ROCm detection.

ROCm support is architecture-specific and Serein does not maintain a
GPU-model-to-support mapping table (S4 brief Section 35/91 — such a
table goes stale immediately and PCI device IDs alone are not a
trustworthy signal). Instead, ``rocm_support`` is derived from real
ROCm *runtime* evidence only:

- ``rocminfo`` absent -> ``supported=None`` (genuinely unknown; AMD
  hardware being present proves nothing about ROCm support on its own).
- ``rocminfo`` present and its output enumerates at least one agent
  with ``Device Type: GPU`` -> ``supported=True``, high confidence —
  this is ROCm's own runtime confirming it recognizes the GPU.
- ``rocminfo`` present but reports no GPU agent -> ``supported=False``,
  high confidence — ROCm is installed and has already made the
  determination that this hardware isn't usable.

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
            supported=None,
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
            supported=None,
            confidence="low",
            reason="rocminfo is installed but did not run successfully; support unknown.",
        )
    if _GPU_AGENT_RE.search(result.stdout):
        return RocmSupportInfo(
            supported=True,
            confidence="high",
            reason="rocminfo enumerates at least one GPU agent.",
        )
    return RocmSupportInfo(
        supported=False,
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
