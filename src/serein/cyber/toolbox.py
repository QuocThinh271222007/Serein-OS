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
