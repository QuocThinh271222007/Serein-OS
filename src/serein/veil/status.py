"""``serein veil status``: a read-only privacy-isolation summary.

Safe to run anywhere (Windows dev host, Ubuntu, WSL, CI, a container) -
every field degrades to an honest "unavailable"/"unknown" rather than
raising. Never lists a real interface name, hostname, username, MAC
address, SSID, public IP, VPN detail, browser history entry, Tor
circuit/relay address, or control-port secret (Section 37-39/91) - only
booleans, small enumerations, and prose reasons are ever surfaced.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment
from serein.veil.browser import detect_ordinary_browser_status, detect_tor_browser_status
from serein.veil.dns import evaluate_dns_privacy
from serein.veil.models import VeilStatusReport
from serein.veil.tor import detect_tor_status
from serein.veil.whonix import detect_whonix_status
from serein.veil.workspace import evaluate_kill_switch, evaluate_workspace_readiness


def build_veil_status(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> VeilStatusReport:
    environment = detect_environment(root)
    tor = detect_tor_status(runner=runner, root=root)
    tor_browser = detect_tor_browser_status(runner=runner)

    return VeilStatusReport(
        schema_version=1,
        tor=tor,
        tor_browser=tor_browser,
        ordinary_browser=detect_ordinary_browser_status(runner=runner),
        dns=evaluate_dns_privacy(tor),
        kill_switch=evaluate_kill_switch(),
        workspace=evaluate_workspace_readiness(tor, tor_browser, environment.is_container),
        whonix=detect_whonix_status(runner=runner, root=root, home=home),
    )
