"""NVIDIA GPU/driver/CUDA detection.

Every signal here is read-only and safe: ``nvidia-smi`` (no args, plus
one narrow ``--query-gpu`` call) never mutates GPU state, and every
filesystem check is a plain existence/listing test (never a content
scan, never arbitrary user files). The driver-reported CUDA *driver
API* version and the separately-installed CUDA *Toolkit* are
deliberately kept in two different fields on ``NvidiaStatus`` —
conflating them is the single most common mistake in this space (S4
brief Section 16), and this module exists specifically to not make it.

``cuda_toolkit_installed`` is computed from STRONG evidence only —
``nvcc --version`` succeeding, or dpkg reporting the ``cuda-toolkit``
package genuinely installed (reusing ``serein.development.dpkg``
rather than duplicating package-query infrastructure, S4R Section 17).
A bare ``/usr/local/cuda*`` marker existing is real but weaker
evidence — an empty directory or a stale symlink left over from a
partial/removed install previously produced a false positive here
(S4R Section 16/19 corrective) — so it is tracked separately as
``cuda_toolkit_marker_present`` and never on its own sets
``cuda_toolkit_installed``.
"""

from __future__ import annotations

import re
from pathlib import Path

from serein.ai.models import NvidiaStatus, VRAMInfo, classify_vram_tier
from serein.development.dpkg import apt_package_installed
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.models import GPUPolicyInfo

_DRIVER_VERSION_RE = re.compile(r"Driver Version:\s*([\d.]+)")
_CUDA_DRIVER_API_RE = re.compile(r"CUDA Version:\s*([\d.]+)")


def _query_driver_and_cuda_version(runner: CommandRunner) -> tuple[str | None, str | None]:
    """One `nvidia-smi` call gives both the driver version and the
    CUDA driver-API version in its banner - cheaper than two calls,
    and keeps the two facts textually next to each other in the
    source, reinforcing that they come from the same (driver, not
    toolkit) evidence."""
    result = runner.run(["nvidia-smi"], timeout=5.0)
    if result is None or result.returncode != 0:
        return None, None
    text = result.stdout
    driver_match = _DRIVER_VERSION_RE.search(text)
    cuda_match = _CUDA_DRIVER_API_RE.search(text)
    return (
        driver_match.group(1) if driver_match else None,
        cuda_match.group(1) if cuda_match else None,
    )


def _query_vram(runner: CommandRunner) -> list[VRAMInfo]:
    result = runner.run(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], timeout=5.0
    )
    if result is None or result.returncode != 0:
        return []
    vram: list[VRAMInfo] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            total_mib = int(stripped)
        except ValueError:
            continue
        vram.append(VRAMInfo(total_mib=total_mib, tier=classify_vram_tier(total_mib)))
    return vram


def _cuda_toolkit_marker_present(root: Path) -> bool:
    """A CUDA Toolkit install marker: the canonical ``/usr/local/cuda``
    symlink (or a real directory in its place). Existence only — never
    read for contents. Auxiliary evidence only; see module docstring -
    never sufficient on its own to prove the toolkit is installed."""
    return (root / "usr" / "local" / "cuda").exists()


def _cuda_toolkit_dirs(root: Path) -> list[str]:
    """Real versioned `/usr/local/cuda-*` directory names — a listing,
    never file contents. More than one is real "multiple toolkit
    installed" evidence for the doctor."""
    local_dir = root / "usr" / "local"
    if not local_dir.is_dir():
        return []
    try:
        return sorted(p.name for p in local_dir.iterdir() if p.name.startswith("cuda-"))
    except OSError:
        return []


def detect_nvidia_status(
    gpu_policy: GPUPolicyInfo,
    runner: CommandRunner = DEFAULT_RUNNER,
    root: Path = DEFAULT_ROOT,
) -> NvidiaStatus:
    driver_version, cuda_driver_api_version = _query_driver_and_cuda_version(runner)
    nvidia_smi_status = probe_tool("nvidia-smi", "nvidia-smi", runner=runner)
    driver_usable = driver_version is not None

    nvcc = probe_tool("nvcc", "nvcc", version_args=("--version",), runner=runner)
    toolkit_package_installed = apt_package_installed("cuda-toolkit", runner=runner)
    cuda_toolkit_installed = nvcc.installed or toolkit_package_installed
    marker_present = _cuda_toolkit_marker_present(root)

    nvidia_ctk = probe_tool("nvidia-ctk", "nvidia-ctk", runner=runner)

    return NvidiaStatus(
        hardware_present=gpu_policy.nvidia_present,
        kernel_module_loaded=gpu_policy.nvidia_kernel_module_loaded,
        nvidia_smi=nvidia_smi_status,
        driver_version=driver_version,
        cuda_driver_api_version=cuda_driver_api_version,
        nvcc=nvcc,
        cuda_toolkit_installed=cuda_toolkit_installed,
        cuda_toolkit_marker_present=marker_present,
        cuda_toolkit_dirs=_cuda_toolkit_dirs(root),
        nvidia_ctk=nvidia_ctk,
        vram=_query_vram(runner) if driver_usable else [],
    )
