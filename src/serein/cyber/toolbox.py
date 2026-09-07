"""Isolated cyber toolbox detection and host-hygiene evidence.

Reuses S3's container detection directly (Section 59 — never
re-probed independently); Distrobox + Podman remain S3's architecture,
not reopened here (Section 29/30/31 — a general cyber toolbox is
Ubuntu/Debian-based via Distrobox, not a Kali container by default).

``detect_host_hygiene`` is doctor-support evidence only (Section 24):
a small, explicit set of tools that should never ordinarily live on
the host baseline (they belong in the isolated toolbox or a VM).
Presence is reported, never removed or flagged as an error — a user
may have installed them deliberately.
"""

from __future__ import annotations

from serein.cyber.models import CyberContainerStatusInfo, HostHygieneStatus
from serein.development.containers import detect_container_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_toolbox_status(runner: CommandRunner = DEFAULT_RUNNER) -> CyberContainerStatusInfo:
    dev_status = detect_container_status(runner)
    return CyberContainerStatusInfo(
        podman=dev_status.podman,
        docker=dev_status.docker,
        distrobox=dev_status.distrobox,
    )


def container_toolbox_installed(containers: CyberContainerStatusInfo) -> bool:
    """A "container toolbox" is the engine *and* Distrobox together
    (Section 2-3 of the S5RM corrective) - an engine alone (or Distrobox
    alone, with no engine to back it) is not a complete, usable toolbox
    subsystem, so it must not be reported as ``installed``."""
    engine_present = containers.podman.installed or containers.docker.installed
    return engine_present and containers.distrobox.installed


def container_toolbox_reason(containers: CyberContainerStatusInfo) -> str:
    """Reason text that reflects which half (engine/Distrobox) is
    actually present, rather than always claiming both are confirmed
    (Section 6 of the S5RM corrective)."""
    engine_present = containers.podman.installed or containers.docker.installed
    distrobox_present = containers.distrobox.installed
    if engine_present and distrobox_present:
        return (
            "A supported container engine and Distrobox are installed; "
            "runtime usability remains unverified because Serein does not "
            "create/run a container during detection (S5R Section 32-34)."
        )
    if engine_present and not distrobox_present:
        return "A container engine is installed, but Distrobox is not."
    if distrobox_present and not engine_present:
        return "Distrobox is installed, but no supported container engine is detected."
    return "No container engine or Distrobox installation is detected."


def detect_host_hygiene(runner: CommandRunner = DEFAULT_RUNNER) -> HostHygieneStatus:
    return HostHygieneStatus(
        hashcat=probe_tool("hashcat", "hashcat", version_args=("--version",), runner=runner),
        john=probe_tool("john", "john", runner=runner),
        metasploit=probe_tool(
            "msfconsole", "msfconsole", version_args=("--version",), runner=runner
        ),
        sqlmap=probe_tool("sqlmap", "sqlmap", version_args=("--version",), runner=runner),
        aircrack_ng=probe_tool(
            "aircrack-ng", "aircrack-ng", version_args=("--help",), runner=runner
        ),
    )
