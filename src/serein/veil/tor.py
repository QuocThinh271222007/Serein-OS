"""Tor client detection: package/binary/service/config/SOCKS evidence.

Every question Section 6 lists is kept genuinely separate - this module
never collapses "installed" into "usable". The only network activity
this module ever performs is a local, read-only listening-socket check
(``/proc/net/tcp``/``/proc/net/tcp6``) for Tor's default SOCKS port -
never an external connection, never ``check.torproject.org``, never a
real SOCKS handshake (Section 44).

``systemctl`` unit naming for Tor's Debian/Ubuntu package is not
hardcoded to a single name (Section 43): both ``tor.service`` (the
package's own top-level unit) and ``tor@default.service`` (the
multi-instance template's default instance, used by some
configurations) are tried, in that order, and neither call assumes
systemd is even present - a host with no systemd (many WSL
configurations, some containers) reports ``service_present=None``
("unknown"), never ``False`` ("confirmed absent").
"""

from __future__ import annotations

import re
from pathlib import Path

from serein.development.dpkg import apt_package_installed
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware._util import DEFAULT_ROOT, read_text
from serein.veil.models import TorConfigStatus, TorStatusInfo

_TOR_SERVICE_UNIT_CANDIDATES: tuple[str, ...] = ("tor.service", "tor@default.service")

#: Tor's compiled-in default SOCKS port (127.0.0.1:9050) - the only port
#: this module ever checks for a local listener (Section 45).
_DEFAULT_SOCKS_PORT = 9050

_DIRECTIVE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s+(.*)$")

_TRISTATE_DIRECTIVES: tuple[str, ...] = ("SocksPort", "ControlPort", "CookieAuthentication")
_PRESENCE_ONLY_DIRECTIVES: tuple[str, ...] = ("TransPort", "DNSPort", "DataDirectory")


def _iter_torrc_lines(root: Path) -> list[str]:
    paths = [root / "etc" / "tor" / "torrc"]
    torrc_d = root / "etc" / "tor" / "torrc.d"
    if torrc_d.is_dir():
        try:
            paths.extend(sorted(p for p in torrc_d.iterdir() if p.is_file()))
        except OSError:
            pass
    lines: list[str] = []
    for path in paths:
        text = read_text(path)
        if not text:
            continue
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
    return lines


def _directive_value(lines: list[str], name: str) -> str | None:
    lowered = name.lower()
    for line in lines:
        match = _DIRECTIVE_RE.match(line)
        if match and match.group(1).lower() == lowered:
            return match.group(2).strip()
    return None


def _tri_state(lines: list[str], name: str) -> bool | None:
    value = _directive_value(lines, name)
    if value is None:
        return None
    return value not in ("0", "")


def parse_tor_config(root: Path = DEFAULT_ROOT) -> TorConfigStatus:
    """Read-only ``torrc``/``torrc.d`` parsing - never exposes a
    directive's raw value (only a booleans-derived summary), and never
    reads bridge line text, cookie file contents, or hashed passwords
    (Section 39-41/92)."""
    main_present = (root / "etc" / "tor" / "torrc").is_file()
    lines = _iter_torrc_lines(root)
    bridge_present = any(line.lower().startswith("bridge ") for line in lines)
    return TorConfigStatus(
        config_present=main_present or bool(lines),
        socks_port_configured=_tri_state(lines, "SocksPort"),
        control_port_configured=_tri_state(lines, "ControlPort"),
        cookie_authentication_configured=_tri_state(lines, "CookieAuthentication"),
        trans_port_configured=_directive_value(lines, "TransPort") is not None,
        dns_port_configured=_directive_value(lines, "DNSPort") is not None,
        data_directory_configured=_directive_value(lines, "DataDirectory") is not None,
        bridge_lines_present=bridge_present,
    )


def _probe_tor_service(runner: CommandRunner) -> tuple[bool | None, bool | None, str]:
    systemctl_available = False
    for unit in _TOR_SERVICE_UNIT_CANDIDATES:
        result = runner.run(["systemctl", "is-enabled", unit], timeout=3.0)
        if result is None:
            continue
        systemctl_available = True
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "not-found" in combined:
            continue
        active_result = runner.run(["systemctl", "is-active", unit], timeout=3.0)
        active = bool(active_result and active_result.stdout.strip().lower() == "active")
        return True, active, unit
    if systemctl_available:
        return False, False, ""
    return None, None, ""


def _local_socks_listener_present(root: Path) -> bool | None:
    """Read-only ``/proc/net/tcp[6]`` scan for a LISTEN-state socket on
    Tor's default SOCKS port. Never connects anywhere (Section 44-45);
    a different process listening on 9050 would be a false positive,
    which is why this is only ever combined evidence, never sole proof,
    of Tor usability."""
    found_any_table = False
    port_hex = f"{_DEFAULT_SOCKS_PORT:04X}"
    for rel in ("proc/net/tcp", "proc/net/tcp6"):
        text = read_text(root / rel)
        if text is None:
            continue
        found_any_table = True
        for line in text.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4:
                continue
            local_address, state = fields[1], fields[3]
            if ":" not in local_address:
                continue
            _addr, _, local_port = local_address.partition(":")
            if local_port.upper() == port_hex and state.upper() == "0A":
                return True
    return False if found_any_table else None


def _evaluate_tor_usable(
    binary_installed: bool,
    service_present: bool | None,
    service_active: bool | None,
    service_unit: str,
    socks_configured: bool | None,
    socks_listener_detected: bool | None,
) -> tuple[bool | None, str, str]:
    if not binary_installed:
        return False, "high", "Tor is not installed on this host."
    if service_present is None:
        return (
            None, "low",
            "Tor is installed, but its service state could not be determined "
            "(no systemd/systemctl detected) - usability is unknown, never "
            "assumed.",
        )
    if not service_present:
        return (
            False, "medium",
            "Tor is installed but no tor systemd service unit was found - it "
            "is not currently running as a managed service.",
        )
    if not service_active:
        unit_label = service_unit or "the tor service"
        return False, "high", f"{unit_label} exists but is not active."
    if socks_configured is False:
        return (
            False, "high",
            "The tor service is active, but SocksPort is explicitly "
            "disabled (SocksPort 0) in torrc.",
        )
    if socks_configured is True or socks_listener_detected is True:
        return (
            True, "medium",
            "The tor service is active and a SOCKS listener is configured/"
            "detected. This confirms Tor client usability only - it does "
            "NOT mean any application is actually routed through it "
            "(Section 7), and does not by itself prove DNS-leak protection.",
        )
    return (
        None, "low",
        "The tor service is active, but no explicit SocksPort directive or "
        "local SOCKS listener was found. Tor's own built-in default "
        "(SocksPort 9050) may still apply, but Serein does not assume "
        "that (Section 41) - usability stays unknown.",
    )


def detect_tor_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> TorStatusInfo:
    binary = probe_tool("tor", "tor", version_args=("--version",), runner=runner)
    package_installed = binary.installed or apt_package_installed("tor", runner=runner)
    torsocks = probe_tool("torsocks", "torsocks", version_args=("--version",), runner=runner)
    nyx = probe_tool("nyx", "nyx", version_args=("--version",), runner=runner)
    obfs4proxy = probe_tool("obfs4proxy", "obfs4proxy", version_args=("-version",), runner=runner)

    service_present, service_active, service_unit = _probe_tor_service(runner)
    config = parse_tor_config(root)
    socks_listener_detected = _local_socks_listener_present(root)

    usable, confidence, reason = _evaluate_tor_usable(
        package_installed, service_present, service_active, service_unit,
        config.socks_port_configured, socks_listener_detected,
    )

    return TorStatusInfo(
        package_installed=package_installed,
        binary=binary,
        torsocks=torsocks,
        nyx=nyx,
        obfs4proxy=obfs4proxy,
        service_present=service_present,
        service_active=service_active,
        service_unit=service_unit,
        config=config,
        socks_listener_detected=socks_listener_detected,
        usable=usable,
        confidence=confidence,
        reason=reason,
    )
