"""AI container-runtime detection.

Reuses S3's ``detect_container_status`` for podman/docker/distrobox
directly (Section 86 — never re-probed independently) and adds the
NVIDIA-specific GPU-container layer: NVIDIA Container Toolkit presence
and whether a real CDI spec for NVIDIA has been generated. CDI
(Container Device Interface) is the current, non-obsolete mechanism
for GPU passthrough and works with both Docker and Podman — Serein
does not special-case one engine over the other for AI container
support (see docs/ai/container-strategy.md and ADR-0011, which S4 does
not reopen). Detection never starts a daemon, never generates a CDI
spec, and never inspects container contents.
"""

from __future__ import annotations

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


def _cdi_nvidia_present(root: Path) -> bool:
    return any(root.joinpath(*parts).is_file() for parts in _CDI_NVIDIA_PATHS)


def detect_ai_container_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> AIContainerStatusInfo:
    dev_status = detect_container_status(runner)
    return AIContainerStatusInfo(
        podman=dev_status.podman,
        docker=dev_status.docker,
        distrobox=dev_status.distrobox,
        nvidia_container_toolkit=probe_tool("nvidia-ctk", "nvidia-ctk", runner=runner),
        cdi_nvidia_generated=_cdi_nvidia_present(root),
    )
