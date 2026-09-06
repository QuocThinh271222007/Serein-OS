"""GPU topology policy: hybrid-graphics and compute-driver detection.

Builds on ``serein.hardware.gpu.detect_gpus`` (vendor/kind per DRM node)
rather than re-enumerating ``/sys/class/drm`` — see
``docs/hardware/gpu-policy.md`` for what this module deliberately does
NOT do (no driver install, no overclocking, no GPU switching).
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import GPUDevice, GPUPolicyInfo


def _kernel_module_loaded(root: Path, module: str) -> bool:
    modules_text = read_text(root / "proc" / "modules")
    if modules_text:
        for line in modules_text.splitlines():
            fields = line.split()
            if fields and fields[0] == module:
                return True
    return (root / "sys" / "module" / module).is_dir()


def detect_gpu_policy(root: Path, gpus: list[GPUDevice]) -> GPUPolicyInfo:
    integrated_count = sum(1 for g in gpus if g.kind == "integrated")
    discrete_count = sum(1 for g in gpus if g.kind == "discrete")
    nvidia_present = any(g.vendor == "NVIDIA" for g in gpus)

    return GPUPolicyInfo(
        hybrid=integrated_count > 0 and discrete_count > 0,
        nvidia_present=nvidia_present,
        nvidia_kernel_module_loaded=_kernel_module_loaded(root, "nvidia"),
        amdgpu_kernel_module_loaded=_kernel_module_loaded(root, "amdgpu"),
        integrated_count=integrated_count,
        discrete_count=discrete_count,
    )
