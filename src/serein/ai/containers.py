"""AI container-runtime detection.

Reuses S3's ``detect_container_status`` for podman/docker/distrobox
directly (Section 86 — never re-probed independently) and adds the
NVIDIA-specific GPU-container layer: NVIDIA Container Toolkit presence
and whether NVIDIA CDI integration is evidenced. CDI (Container Device
Interface) is the current, non-obsolete mechanism for GPU passthrough
and works with both Docker and Podman — Serein does not special-case
one engine over the other for AI container support (see
docs/ai/container-strategy.md and ADR-0011, which S4 does not reopen).

CDI evidence uses two read-only sources (S4R Section 27/28 — current
NVIDIA Container Toolkit releases can generate/manage CDI specs
automatically, so a static file is not the only valid signal):
a real spec file existing at one of the well-known paths, or a
successful ``nvidia-ctk cdi list`` reporting a real NVIDIA device
entry. Detection never starts a daemon, never runs
``nvidia-ctk cdi generate``, and never inspects container contents.
"""

from __future__ import annotations

import re
from pathlib import Path

from serein.ai.models import AIContainerStatusInfo
from serein.development.containers import detect_container_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware._util import DEFAULT_ROOT

_CDI_NVIDIA_PATHS = (
    ("etc", "cdi", "nvidia.yaml"),
    ("var", "run", "cdi", "nvidia.yaml"),
)
_CDI_NVIDIA_DEVICE_RE = re.compile(r"nvidia\.com/gpu")


def _cdi_nvidia_marker_present(root: Path) -> bool:
    return any(root.joinpath(*parts).is_file() for parts in _CDI_NVIDIA_PATHS)


def _cdi_nvidia_listed(runner: CommandRunner) -> bool:
    """Read-only ``nvidia-ctk cdi list`` query — real evidence the
    toolkit currently has an NVIDIA CDI device registered, whether it
    came from a static spec file or was generated automatically.
    Never runs ``nvidia-ctk cdi generate``."""
    result = runner.run(["nvidia-ctk", "cdi", "list"], timeout=5.0)
    if result is None or result.returncode != 0:
        return False
    return bool(_CDI_NVIDIA_DEVICE_RE.search(result.stdout))


def detect_ai_container_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> AIContainerStatusInfo:
    dev_status = detect_container_status(runner)
    cdi_evidence = _cdi_nvidia_marker_present(root) or _cdi_nvidia_listed(runner)
    return AIContainerStatusInfo(
        podman=dev_status.podman,
        docker=dev_status.docker,
        distrobox=dev_status.distrobox,
        nvidia_container_toolkit=probe_tool("nvidia-ctk", "nvidia-ctk", runner=runner),
        cdi_nvidia_generated=cdi_evidence,
    )
