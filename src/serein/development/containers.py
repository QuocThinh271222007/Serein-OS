"""Container engine detection.

Detection never starts a daemon, never creates a container, and never
inspects container contents — it is limited to ``<tool> --version``,
which for both Podman and Docker's CLI succeeds without a running
daemon. See docs/development/container-strategy.md for why Podman is
the preferred default and Docker/Distrobox's exact roles.
"""

from __future__ import annotations

from serein.development.models import ContainerStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware.models import EnvironmentInfo


def detect_container_status(runner: CommandRunner = DEFAULT_RUNNER) -> ContainerStatusInfo:
    return ContainerStatusInfo(
        podman=probe_tool("podman", "podman", runner=runner),
        docker=probe_tool("docker", "docker", runner=runner),
        distrobox=probe_tool("distrobox", "distrobox", runner=runner),
    )


def container_capability_available(environment: EnvironmentInfo) -> bool:
    """Single source of truth for "can Serein provision a container
    engine/Distrobox here" - shared by capabilities.py and planner.py so
    the two can never diverge (see the S2RM lesson: a planner must never
    propose APPLY where the capability model says unavailable). Only a
    nested-container context is excluded; WSL is fine (rootless Podman
    and Docker Desktop's WSL backend both work there)."""
    return not environment.is_container
