"""Network/DNS/TLS diagnostic tool detection.

Host-safe diagnostics only (Section 6/11) — every probe is a plain
``<binary> --version``-style read-only call via the shared
``CommandRunner``. This module never runs a scan, a probe against any
remote or local target, or any command that touches the network beyond
the tool's own local version banner. ``nmap`` is detected the same
way: presence only, never invoked against a target (Section 10/52).
"""

from __future__ import annotations

from serein.cyber.models import NetworkDiagnosticsStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_network_status(runner: CommandRunner = DEFAULT_RUNNER) -> NetworkDiagnosticsStatus:
    return NetworkDiagnosticsStatus(
        nmap=probe_tool("nmap", "nmap", runner=runner),
        tcpdump=probe_tool("tcpdump", "tcpdump", version_args=("--version",), runner=runner),
        dig=probe_tool("dig", "dig", version_args=("-v",), runner=runner),
        whois=probe_tool("whois", "whois", version_args=("--version",), runner=runner),
        socat=probe_tool("socat", "socat", version_args=("-V",), runner=runner),
        netcat=probe_tool("netcat", "nc", version_args=("-h",), runner=runner),
        mtr=probe_tool("mtr", "mtr", version_args=("--version",), runner=runner),
        ethtool=probe_tool("ethtool", "ethtool", version_args=("--version",), runner=runner),
        openssl=probe_tool("openssl", "openssl", version_args=("version",), runner=runner),
    )
