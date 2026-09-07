"""Tor client detection: package/runtime-service/config/SOCKS evidence.

Every question Section 6 lists is kept genuinely separate - this module
never collapses "installed" into "usable". The only network activity
this module ever performs is a local, read-only listening-socket check
(``/proc/net/tcp``/``/proc/net/tcp6``) for Tor's default SOCKS port -
never an external connection, never ``check.torproject.org``, never a
real SOCKS handshake (Section 44).

**Tor systemd runtime semantics (S6R Corrective A).** Ubuntu 26.04's
``tor`` package ships three units (live-verified against the package's
own file listing): ``tor.service`` (a top-level/master unit),
``tor@.service`` (an uninstantiated multi-instance template), and
``tor@default.service`` (the concrete default-instance unit). Only
``tor@default.service`` is real Tor-*daemon* runtime evidence - a bare
``tor.service active`` result is orchestration state, not proof any Tor
process is actually running, and must never be treated as sufficient
runtime evidence by itself. See ``TorServiceStatus`` in ``models.py``.

**Tor config semantics (S6R Corrective B).** ``torrc`` is parsed
sequentially starting from ``/etc/tor/torrc`` only; ``/etc/tor/torrc.d``
is **never** implicitly merged - it is only read if the main ``torrc``
(or something it includes) contains an explicit ``%include`` directive
referencing it, exactly mirroring real Tor's own config-loading
behavior. ``SocksPort``/``ControlPort``/``TransPort``/``DNSPort`` are
real Tor multi-valued/additive directives (each occurrence can open its
own listener), so they are evaluated as "any enabled occurrence found",
never "first occurrence wins" - an earlier ``SocksPort 0`` line must
never suppress a later, genuinely-enabled ``SocksPort 9050`` line.
``CookieAuthentication`` is a scalar on/off flag and is evaluated as
"last occurrence wins", matching Tor's real override behavior for that
kind of directive.

**Tor usability evidence (S6R Corrective C).** Configuration intent
(an explicit ``SocksPort`` directive) is never, by itself, runtime
proof - ``usable`` requires the Tor daemon *runtime* unit to be
confirmed active *and* a real, local SOCKS listener to actually be
detected. "SocksPort configured, no confirmed listener" is ``None``
(unknown), never ``True``.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from serein.development.dpkg import apt_package_installed
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware._util import DEFAULT_ROOT, read_text
from serein.veil.models import TorConfigStatus, TorServiceStatus, TorStatusInfo

#: Debian/Ubuntu's tor package packaging reality (Section 4-5, live-
#: verified against Ubuntu 26.04's file listing): the master/orchestration
#: unit, and the sole legitimate default-instance runtime unit. No other
#: instance name is wildcard-scanned (Section 4).
_MASTER_UNIT = "tor.service"
_RUNTIME_UNIT_CANDIDATES: tuple[str, ...] = ("tor@default.service",)

#: Tor's compiled-in default SOCKS port (127.0.0.1:9050) - the only port
#: this module ever checks for a local listener (Section 45).
_DEFAULT_SOCKS_PORT = 9050

_DIRECTIVE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s+(.*)$")
_INCLUDE_RE = re.compile(r"^%include\s+(\S+)\s*$", re.IGNORECASE)

#: Real Tor multi-valued/additive directives - "any enabled occurrence
#: found" semantics (Section 12-15), never first-occurrence-wins.
_MULTI_VALUE_DIRECTIVES: tuple[str, ...] = ("SocksPort", "ControlPort", "TransPort", "DNSPort")

#: Guards against a runaway/cyclic %include chain (Section 10).
_MAX_INCLUDE_DEPTH = 8


# ---------------------------------------------------------------------------
# torrc parsing (%include-aware, never an implicit torrc.d merge)
# ---------------------------------------------------------------------------


def _include_target_path(root: Path, raw: str, current_dir: Path) -> Path:
    """Resolves a ``%include`` argument *under the injected root* even
    when the argument is an absolute-looking path (e.g. the real
    ``/etc/tor/torrc.d``) - never the real host filesystem root, so
    tests stay isolated regardless of what path a fixture torrc names."""
    pure = PurePosixPath(raw)
    if pure.is_absolute():
        return root.joinpath(*pure.parts[1:])
    return current_dir / raw


def _resolve_lines(root: Path, path: Path, seen: frozenset[Path], depth: int) -> list[str]:
    if depth > _MAX_INCLUDE_DEPTH or path in seen:
        return []
    seen = seen | {path}

    if path.is_dir():
        try:
            children = sorted(p for p in path.iterdir() if p.is_file())
        except OSError:
            return []
        lines: list[str] = []
        for child in children:
            lines.extend(_resolve_lines(root, child, seen, depth + 1))
        return lines

    text = read_text(path)
    if not text:
        return []
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        include_match = _INCLUDE_RE.match(stripped)
        if include_match:
            target = _include_target_path(root, include_match.group(1), path.parent)
            lines.extend(_resolve_lines(root, target, seen, depth + 1))
            continue
        lines.append(stripped)
    return lines


def _effective_torrc_lines(root: Path) -> list[str]:
    """Only ever reads ``/etc/tor/torrc`` and whatever it (transitively)
    ``%include``s - ``/etc/tor/torrc.d`` is never implicitly merged in
    (Section 9): a torrc with no ``%include`` line leaves torrc.d
    entirely unread, exactly like real Tor."""
    main = root / "etc" / "tor" / "torrc"
    if not main.is_file():
        return []
    return _resolve_lines(root, main, frozenset(), 0)


def _all_directive_values(lines: list[str], name: str) -> list[str]:
    lowered = name.lower()
    values = []
    for line in lines:
        match = _DIRECTIVE_RE.match(line)
        if match and match.group(1).lower() == lowered:
            values.append(match.group(2).strip())
    return values


def _multi_value_tri_state(lines: list[str], name: str) -> bool | None:
    """"Any enabled occurrence found" - real Tor semantics for an
    additive/multi-valued directive (Section 13-15/18): multiple
    occurrences each open their own listener, so an earlier ``0`` never
    suppresses a later enabled value."""
    values = _all_directive_values(lines, name)
    if not values:
        return None
    return any(value not in ("0", "") for value in values)


def _single_value_tri_state(lines: list[str], name: str) -> bool | None:
    """"Last occurrence wins" - Tor's real override behavior for a
    scalar on/off directive like ``CookieAuthentication``."""
    values = _all_directive_values(lines, name)
    if not values:
        return None
    return values[-1] not in ("0", "")


def parse_tor_config(root: Path = DEFAULT_ROOT) -> TorConfigStatus:
    """Read-only ``torrc`` (+ explicit ``%include`` targets) parsing -
    never exposes a directive's raw value (only a booleans-derived
    summary), and never reads bridge line text, cookie file contents,
    or hashed passwords (Section 39-41/92)."""
    main_present = (root / "etc" / "tor" / "torrc").is_file()
    lines = _effective_torrc_lines(root)
    bridge_present = any(line.lower().startswith("bridge ") for line in lines)
    return TorConfigStatus(
        config_present=main_present or bool(lines),
        socks_port_configured=_multi_value_tri_state(lines, "SocksPort"),
        control_port_configured=_multi_value_tri_state(lines, "ControlPort"),
        cookie_authentication_configured=_single_value_tri_state(lines, "CookieAuthentication"),
        trans_port_configured=_multi_value_tri_state(lines, "TransPort"),
        dns_port_configured=_multi_value_tri_state(lines, "DNSPort"),
        data_directory_configured=bool(_all_directive_values(lines, "DataDirectory")),
        bridge_lines_present=bridge_present,
    )


# ---------------------------------------------------------------------------
# systemd runtime probing (master unit vs. real runtime instance)
# ---------------------------------------------------------------------------


def _probe_unit(runner: CommandRunner, unit: str) -> tuple[bool | None, bool | None]:
    """Read-only ``is-enabled``/``is-active`` for one unit (Section 6 -
    never ``start``/``enable``/``restart``). ``(None, None)`` if
    systemctl itself could not be probed at all; ``(False, False)`` if
    systemctl ran but reports the unit does not exist; ``(True,
    active)`` otherwise."""
    result = runner.run(["systemctl", "is-enabled", unit], timeout=3.0)
    if result is None:
        return None, None
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "not-found" in combined:
        return False, False
    active_result = runner.run(["systemctl", "is-active", unit], timeout=3.0)
    active = bool(active_result and active_result.stdout.strip().lower() == "active")
    return True, active


def _probe_tor_service(runner: CommandRunner) -> TorServiceStatus:
    master_present, master_active = _probe_unit(runner, _MASTER_UNIT)

    runtime_present: bool | None = None
    runtime_active: bool | None = None
    runtime_name = ""
    runtime_reached = False
    for unit in _RUNTIME_UNIT_CANDIDATES:
        present, active = _probe_unit(runner, unit)
        if present is None:
            continue
        runtime_reached = True
        if present:
            runtime_present, runtime_active, runtime_name = True, active, unit
            break
        runtime_present, runtime_active = False, False

    if not runtime_reached:
        reason = (
            "systemctl could not be probed (no systemd, or systemctl "
            "unavailable) - Tor daemon runtime state is unknown, never "
            "guessed either way."
        )
        return TorServiceStatus(master_present, master_active, None, None, "", reason)

    if runtime_present:
        state = "active" if runtime_active else "not active"
        reason = (
            f"{runtime_name} (the actual Tor daemon runtime instance) is "
            f"{state}. tor.service, even if active, is only a top-level "
            "orchestration unit and is never runtime evidence by itself."
        )
    else:
        reason = (
            "No Tor daemon runtime instance unit (tor@default.service) "
            "was found - tor.service alone, even if active, is not proof "
            "any Tor daemon process is running."
        )
    return TorServiceStatus(
        master_present, master_active, runtime_present, runtime_active, runtime_name, reason
    )


# ---------------------------------------------------------------------------
# Local SOCKS listener evidence (read-only, never external)
# ---------------------------------------------------------------------------


def _local_socks_listener_present(root: Path) -> bool | None:
    """Read-only ``/proc/net/tcp[6]`` scan for a LISTEN-state socket on
    Tor's default SOCKS port. Never connects anywhere (Section 44-45);
    a different process listening on 9050 would be a false positive,
    and a custom (non-default) ``SocksPort`` would be a false negative
    for this specific check (Section 21-22) - Serein has no safe,
    read-only way to tie a listening socket to the Tor process itself,
    so this is only ever medium-confidence, combined evidence alongside
    runtime-service-active, never sole proof of usability."""
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


# ---------------------------------------------------------------------------
# Usability evidence (S6R Corrective C)
# ---------------------------------------------------------------------------


def _evaluate_tor_usable(
    binary_installed: bool,
    runtime_present: bool | None,
    runtime_active: bool | None,
    runtime_unit_name: str,
    socks_configured: bool | None,
    socks_listener_detected: bool | None,
) -> tuple[bool | None, str, str]:
    if not binary_installed:
        return False, "high", "Tor is not installed on this host."
    if runtime_present is None:
        return (
            None, "low",
            "The Tor daemon runtime state could not be determined (no "
            "systemd/systemctl detected) - usability is unknown, never "
            "assumed.",
        )
    if not runtime_present:
        return (
            False, "medium",
            "No Tor daemon runtime instance (tor@default.service) was "
            "found - Tor is not currently running as a managed service, "
            "regardless of tor.service's own state.",
        )
    if not runtime_active:
        unit_label = runtime_unit_name or "the Tor daemon runtime instance"
        return False, "high", f"{unit_label} exists but is not active."
    if socks_configured is False:
        return (
            False, "high",
            "The Tor daemon runtime is active, but SocksPort is "
            "explicitly disabled (SocksPort 0) in the effective torrc.",
        )
    if socks_listener_detected is True:
        return (
            True, "medium",
            "The Tor daemon runtime is active and a local SOCKS listener "
            "was detected on the expected default port - real, combined "
            "runtime + listener evidence. This confirms Tor client "
            "usability only - it does NOT mean any application is "
            "actually routed through it (Section 7), and does not by "
            "itself prove DNS-leak protection.",
        )
    return (
        None, "low",
        "The Tor daemon runtime is active, but no confirmed local SOCKS "
        "listener was found on the expected default port. Configuration "
        "intent (a SocksPort directive) alone is never runtime proof "
        "(Section 20) - a custom SocksPort would also not be detected by "
        "this check (Section 22) - so usability stays unknown.",
    )


def detect_tor_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> TorStatusInfo:
    binary = probe_tool("tor", "tor", version_args=("--version",), runner=runner)
    package_installed = binary.installed or apt_package_installed("tor", runner=runner)
    torsocks = probe_tool("torsocks", "torsocks", version_args=("--version",), runner=runner)
    nyx = probe_tool("nyx", "nyx", version_args=("--version",), runner=runner)
    obfs4proxy = probe_tool("obfs4proxy", "obfs4proxy", version_args=("-version",), runner=runner)

    service = _probe_tor_service(runner)
    config = parse_tor_config(root)
    socks_listener_detected = _local_socks_listener_present(root)

    usable, confidence, reason = _evaluate_tor_usable(
        package_installed, service.runtime_unit_present, service.runtime_unit_active,
        service.runtime_unit_name, config.socks_port_configured, socks_listener_detected,
    )

    return TorStatusInfo(
        package_installed=package_installed,
        binary=binary,
        torsocks=torsocks,
        nyx=nyx,
        obfs4proxy=obfs4proxy,
        service=service,
        config=config,
        socks_listener_detected=socks_listener_detected,
        usable=usable,
        confidence=confidence,
        reason=reason,
    )
