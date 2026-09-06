"""AI container-runtime detection.

Reuses S3's ``detect_container_status`` for podman/docker/distrobox
directly (Section 86 — never re-probed independently) and adds the
NVIDIA-specific GPU-container layer: NVIDIA Container Toolkit presence
and whether NVIDIA CDI integration is evidenced. CDI (Container Device
Interface) is the current, non-obsolete mechanism for GPU passthrough
and works with both Docker and Podman — Serein does not special-case
one engine over the other for AI container support (see
docs/ai/container-strategy.md and ADR-0011, which S4 does not reopen).

CDI evidence is split into two genuinely different signals (S4RM
Section 3-10 — a prior revision treated a static file's mere existence
as equivalent to real integration, which an empty/stale/malformed file
would satisfy without proving anything):

- ``cdi_marker_present`` — a static spec file exists at a well-known
  path. Existence only, contents never read/parsed (no YAML dependency
  — Section 7). Auxiliary evidence only; never sufficient alone.
- ``cdi_nvidia_resolved`` — a read-only ``nvidia-ctk cdi list`` query
  actually resolved a real ``nvidia.com/gpu`` device entry. This is the
  strong signal capability/doctor usability decisions key off of,
  since current NVIDIA Container Toolkit releases can generate/manage
  CDI state dynamically — the static file is not authoritative on its
  own in either direction.

Detection never starts a daemon, never runs ``nvidia-ctk cdi
generate``, and never inspects container contents.
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


def _cdi_marker_present(root: Path) -> bool:
    """Existence-only check for a static CDI spec file — never read
    for contents, never parsed as YAML. Auxiliary evidence only; see
    module docstring."""
    return any(root.joinpath(*parts).is_file() for parts in _CDI_NVIDIA_PATHS)


def _cdi_nvidia_resolved(runner: CommandRunner) -> bool:
    """Read-only ``nvidia-ctk cdi list`` query — the strong evidence
    signal. Never runs ``nvidia-ctk cdi generate``."""
    result = runner.run(["nvidia-ctk", "cdi", "list"], timeout=5.0)
    if result is None or result.returncode != 0:
        return False
    return bool(_CDI_NVIDIA_DEVICE_RE.search(result.stdout))


def detect_ai_container_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> AIContainerStatusInfo:
    dev_status = detect_container_status(runner)
    return AIContainerStatusInfo(
        podman=dev_status.podman,
        docker=dev_status.docker,
        distrobox=dev_status.distrobox,
        nvidia_container_toolkit=probe_tool("nvidia-ctk", "nvidia-ctk", runner=runner),
        cdi_marker_present=_cdi_marker_present(root),
        cdi_nvidia_resolved=_cdi_nvidia_resolved(runner),
    )
