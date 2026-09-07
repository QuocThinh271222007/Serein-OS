"""Veil (S6) subsystem tests. Every detection call uses a
FakeCommandRunner and an injected root/home - never the real host's
PATH, filesystem, real Tor daemon, real KVM, or real home directory, so
tests are independent of whatever happens to be installed on the
machine running them. No test performs a real SOCKS handshake, a real
network connection, a VM/container creation, a Whonix image download,
or a Tor Browser download."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from serein.development.runner import CommandResult
from serein.doctor.models import CheckStatus
from serein.veil.browser import detect_ordinary_browser_status, detect_tor_browser_status
from serein.veil.capabilities import build_veil_capabilities
from serein.veil.components import all_components, vm_components, workspace_components
from serein.veil.dns import evaluate_dns_privacy
from serein.veil.doctor import run_veil_checks
from serein.veil.models import (
    PRIVACY_LEVELS,
    VEIL_CATEGORIES,
    VEIL_TIERS,
    TorStatusInfo,
)
from serein.veil.planner import VALID_COMPONENTS, build_veil_plan
from serein.veil.status import build_veil_status
from serein.veil.tor import _parse_directive_line, detect_tor_status, parse_tor_config
from serein.veil.whonix import detect_whonix_status
from serein.veil.workspace import evaluate_kill_switch, evaluate_workspace_readiness


class FakeCommandRunner:
    """Maps either an exact argv tuple or a bare binary name to a
    canned CommandResult (or None = "not found"). Records every call
    for tests that need to assert on invocation without ever actually
    running anything."""

    def __init__(self, responses: dict[str | tuple[str, ...], CommandResult | None]):
        self._responses = responses
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):
        self.calls.append(list(args))
        key = tuple(args)
        if key in self._responses:
            return self._responses[key]
        binary = args[0]
        if binary in self._responses:
            return self._responses[binary]
        return None


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _fail(returncode: int = 1, stderr: str = "not found") -> CommandResult:
    return CommandResult(returncode=returncode, stdout="", stderr=stderr)


def _empty_root(tmp_path: Path, name: str = "root") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _root_with_torrc(
    tmp_path: Path,
    lines: list[str],
    torrc_d: dict[str, str] | None = None,
    root: Path | None = None,
) -> Path:
    root = root if root is not None else _empty_root(tmp_path, "root")
    tor_dir = root / "etc" / "tor"
    tor_dir.mkdir(parents=True, exist_ok=True)
    (tor_dir / "torrc").write_text("\n".join(lines), encoding="utf-8")
    if torrc_d:
        d = tor_dir / "torrc.d"
        d.mkdir(parents=True, exist_ok=True)
        for name, content in torrc_d.items():
            (d / name).write_text(content, encoding="utf-8")
    return root


def _add_listener(root: Path, port: int, state: str = "0A") -> Path:
    net_dir = root / "proc" / "net"
    net_dir.mkdir(parents=True, exist_ok=True)
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
    hexport = f"{port:04X}"
    line = (
        f"   0: 00000000:{hexport} 00000000:0000 {state} "
        "00000000:00000000 00:00000000 00000000     0        0 12345 1 0 100 0 0 10 0"
    )
    (net_dir / "tcp").write_text(header + "\n" + line + "\n", encoding="utf-8")
    (net_dir / "tcp6").write_text(header + "\n", encoding="utf-8")
    return root


def _root_with_listener(tmp_path: Path, port: int, state: str = "0A") -> Path:
    return _add_listener(_empty_root(tmp_path, "root"), port, state)


def _add_empty_proc_net(root: Path) -> Path:
    net_dir = root / "proc" / "net"
    net_dir.mkdir(parents=True, exist_ok=True)
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
    (net_dir / "tcp").write_text(header + "\n", encoding="utf-8")
    (net_dir / "tcp6").write_text(header + "\n", encoding="utf-8")
    return root


def _root_with_empty_proc_net(tmp_path: Path) -> Path:
    return _add_empty_proc_net(_empty_root(tmp_path, "root"))


#: Standard FakeCommandRunner responses for "tor@default.service active"
#: - the real Tor daemon runtime evidence (S6R Corrective A).
def _runtime_active_runner(extra: dict | None = None) -> FakeCommandRunner:
    responses = {
        "tor": _ok("Tor version 0.4.9.11."),
        ("systemctl", "is-enabled", "tor@default.service"): _ok("enabled"),
        ("systemctl", "is-active", "tor@default.service"): _ok("active"),
    }
    if extra:
        responses.update(extra)
    return FakeCommandRunner(responses)


def _kvm_ready_root(tmp_path: Path, module_loaded: bool = True) -> Path:
    root = _empty_root(tmp_path, "root")
    (root / "dev").mkdir(parents=True, exist_ok=True)
    (root / "dev" / "kvm").write_text("", encoding="utf-8")
    if module_loaded:
        (root / "proc").mkdir(parents=True, exist_ok=True)
        (root / "proc" / "modules").write_text("kvm 12345 0 - Live 0x0\n", encoding="utf-8")
    return root


def _ready_vm_runner() -> FakeCommandRunner:
    return FakeCommandRunner({
        "qemu-system-x86_64": _ok("QEMU emulator version 8.2.2"),
        "virsh": _ok("6.0.0"),
    })


def _empty_home(tmp_path: Path, name: str = "home") -> Path:
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    return home


def _home_with_images(tmp_path: Path, gateway: bool = False, workstation: bool = False) -> Path:
    home = _empty_home(tmp_path)
    images_dir = home / ".local" / "share" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    if gateway:
        (images_dir / "Whonix-Gateway.qcow2").write_text("", encoding="utf-8")
    if workstation:
        (images_dir / "Whonix-Workstation.qcow2").write_text("", encoding="utf-8")
    return home


# ---------------------------------------------------------------------------
# Tor (Section 6-7, 94)
# ---------------------------------------------------------------------------


class TestTor:
    def test_tor_absent(self, tmp_path):
        root = _empty_root(tmp_path)
        status = detect_tor_status(runner=FakeCommandRunner({}), root=root)
        assert status.package_installed is False
        assert status.usable is False
        assert status.confidence == "high"

    def test_master_active_alone_is_not_runtime_active(self, tmp_path):
        # S6R Corrective A: tor.service active, tor@default.service
        # absent - must never satisfy runtime-active evidence.
        root = _empty_root(tmp_path)
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor.service"): _ok("active"),
            ("systemctl", "is-enabled", "tor@default.service"): _fail(
                4, "Unit tor@default.service not-found."
            ),
        })
        status = detect_tor_status(runner=runner, root=root)
        assert status.service.master_unit_active is True
        assert status.service.runtime_unit_active is not True
        assert status.service.service_active is not True
        assert status.usable is False

    def test_master_active_runtime_inactive(self, tmp_path):
        root = _empty_root(tmp_path)
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor.service"): _ok("active"),
            ("systemctl", "is-enabled", "tor@default.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor@default.service"): CommandResult(3, "inactive", ""),
        })
        status = detect_tor_status(runner=runner, root=root)
        assert status.service.master_unit_active is True
        assert status.service.runtime_unit_active is False
        assert status.usable is False

    def test_master_inactive_runtime_active(self, tmp_path):
        root = _empty_root(tmp_path)
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor.service"): CommandResult(3, "inactive", ""),
            ("systemctl", "is-enabled", "tor@default.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor@default.service"): _ok("active"),
        })
        status = detect_tor_status(runner=runner, root=root)
        assert status.service.master_unit_active is False
        assert status.service.runtime_unit_active is True
        assert status.service.service_active is True

    def test_runtime_active_implies_service_active_true(self, tmp_path):
        root = _root_with_empty_proc_net(tmp_path)
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.service.service_active is True

    def test_systemctl_unavailable_is_unknown_not_false(self, tmp_path):
        # No systemd at all (e.g. some WSL configurations) - runtime
        # state must be None, never guessed False.
        root = _empty_root(tmp_path)
        runner = FakeCommandRunner({"tor": _ok("Tor version 0.4.9.11.")})
        status = detect_tor_status(runner=runner, root=root)
        assert status.package_installed is True
        assert status.service.master_unit_present is None
        assert status.service.runtime_unit_present is None
        assert status.service.runtime_unit_active is None
        assert status.usable is None
        assert status.confidence == "low"

    def test_runtime_unit_absent_confirmed_is_false_not_none(self, tmp_path):
        root = _empty_root(tmp_path)
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor.service"): _fail(4, "Unit tor.service not-found."),
            ("systemctl", "is-enabled", "tor@default.service"): _fail(
                4, "Unit tor@default.service not-found."
            ),
        })
        status = detect_tor_status(runner=runner, root=root)
        assert status.service.runtime_unit_present is False
        assert status.usable is False

    def test_control_port_absent_is_unknown(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 9050"])
        config = parse_tor_config(root)
        assert config.control_port_configured is None

    def test_control_port_present_is_true(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["ControlPort 9051"])
        config = parse_tor_config(root)
        assert config.control_port_configured is True

    def test_control_port_explicitly_zero_is_false(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["ControlPort 0"])
        config = parse_tor_config(root)
        assert config.control_port_configured is False

    def test_never_performs_a_real_socks_handshake_or_external_connection(self, tmp_path):
        root = _add_listener(_root_with_torrc(tmp_path, ["SocksPort 9050"]), 9050)
        runner = _runtime_active_runner()
        detect_tor_status(runner=runner, root=root)
        for call in runner.calls:
            joined = " ".join(call).lower()
            assert "check.torproject.org" not in joined
            assert "curl" not in joined
            assert ".onion" not in joined
            assert "systemctl start" not in joined
            assert "systemctl enable" not in joined
            assert "systemctl restart" not in joined


# ---------------------------------------------------------------------------
# Tor config parsing / secret safety (Section 8-18, 39-41, 92, 95)
# ---------------------------------------------------------------------------


class TestTorConfig:
    def test_no_config_present(self, tmp_path):
        root = _empty_root(tmp_path)
        config = parse_tor_config(root)
        assert config.config_present is False
        assert config.socks_port_configured is None

    def test_torrc_d_not_included_by_default(self, tmp_path):
        # S6R Corrective B, Section 9/18: torrc.d files exist but the
        # main torrc has no %include - must NOT affect effective config.
        root = _root_with_torrc(
            tmp_path, ["SocksPort 9050"], torrc_d={"50-extra.conf": "ControlPort 9051\n"}
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is True
        assert config.control_port_configured is None

    def test_include_directive_pulls_in_torrc_d_at_position(self, tmp_path):
        root = _root_with_torrc(
            tmp_path,
            ["ControlPort 9051", "%include /etc/tor/torrc.d", "DataDirectory /var/lib/tor"],
            torrc_d={"50-socks.conf": "SocksPort 9050\n"},
        )
        config = parse_tor_config(root)
        assert config.config_present is True
        assert config.socks_port_configured is True
        assert config.control_port_configured is True
        assert config.data_directory_configured is True

    def test_include_single_file(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["%include /etc/tor/torrc.d/50-socks.conf"])
        d = root / "etc" / "tor" / "torrc.d"
        d.mkdir(parents=True, exist_ok=True)
        (d / "50-socks.conf").write_text("SocksPort 9050\n", encoding="utf-8")
        config = parse_tor_config(root)
        assert config.socks_port_configured is True

    def test_include_cycle_is_guarded(self, tmp_path):
        # A torrc that (directly or indirectly) includes itself must
        # never infinite-loop - the cycle guard breaks it silently.
        root = _root_with_torrc(tmp_path, ["%include /etc/tor/torrc", "SocksPort 9050"])
        config = parse_tor_config(root)
        assert config.config_present is True

    def test_multiple_socksport_any_enabled_wins(self, tmp_path):
        # Section 13/18: an earlier disabled entry must never suppress
        # a later, genuinely-enabled entry.
        root = _root_with_torrc(tmp_path, ["SocksPort 0", "SocksPort 9050"])
        config = parse_tor_config(root)
        assert config.socks_port_configured is True

    def test_socksport_all_disabled_is_false(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 0"])
        config = parse_tor_config(root)
        assert config.socks_port_configured is False

    def test_socksport_absent_is_none(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["ControlPort 9051"])
        config = parse_tor_config(root)
        assert config.socks_port_configured is None

    def test_multiple_enabled_socksport_is_true(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 9050", "SocksPort 9150"])
        config = parse_tor_config(root)
        assert config.socks_port_configured is True

    def test_control_port_zero_is_false(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["ControlPort 0"])
        config = parse_tor_config(root)
        assert config.control_port_configured is False

    def test_dns_port_zero_is_false(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["DNSPort 0"])
        config = parse_tor_config(root)
        assert config.dns_port_configured is False

    def test_dns_port_enabled_is_true(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["DNSPort 5353"])
        config = parse_tor_config(root)
        assert config.dns_port_configured is True

    def test_trans_port_zero_is_false(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["TransPort 0"])
        config = parse_tor_config(root)
        assert config.trans_port_configured is False

    def test_trans_port_enabled_is_true(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["TransPort 9040"])
        config = parse_tor_config(root)
        assert config.trans_port_configured is True

    def test_trans_port_and_dns_port_absent_is_none(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 9050"])
        config = parse_tor_config(root)
        assert config.trans_port_configured is None
        assert config.dns_port_configured is None

    def test_data_directory_presence_only(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["DataDirectory /var/lib/tor"])
        config = parse_tor_config(root)
        assert config.data_directory_configured is True

    def test_cookie_authentication_last_occurrence_wins(self, tmp_path):
        # Scalar/override directive - last occurrence wins (Section 15).
        root = _root_with_torrc(tmp_path, ["CookieAuthentication 1", "CookieAuthentication 0"])
        config = parse_tor_config(root)
        assert config.cookie_authentication_configured is False

    def test_cookie_authentication_tri_state(self, tmp_path):
        enabled = parse_tor_config(_root_with_torrc(tmp_path / "a", ["CookieAuthentication 1"]))
        disabled = parse_tor_config(_root_with_torrc(tmp_path / "b", ["CookieAuthentication 0"]))
        absent = parse_tor_config(_empty_root(tmp_path / "c"))
        assert enabled.cookie_authentication_configured is True
        assert disabled.cookie_authentication_configured is False
        assert absent.cookie_authentication_configured is None

    def test_bridge_line_presence_never_leaks_the_line_itself(self, tmp_path):
        secret_bridge = "Bridge obfs4 203.0.113.5:443 ABCDEF0123456789 cert=SUPERSECRET"
        secret_hashed = "HashedControlPassword 16:AAAABBBBCCCCDDDDEEEEFFFF0011223344"
        root = _root_with_torrc(tmp_path, [secret_bridge, secret_hashed])
        config = parse_tor_config(root)
        assert config.bridge_lines_present is True
        dumped = json.dumps(asdict(config))
        assert "203.0.113.5" not in dumped
        assert "ABCDEF0123456789" not in dumped
        assert "AAAABBBBCCCCDDDDEEEEFFFF0011223344" not in dumped
        assert "SUPERSECRET" not in dumped

    def test_include_never_leaks_secrets_either(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d"],
            torrc_d={"50-bridge.conf": "Bridge obfs4 198.51.100.9:443 DEADBEEF1234\n"},
        )
        config = parse_tor_config(root)
        assert config.bridge_lines_present is True
        dumped = json.dumps(asdict(config))
        assert "198.51.100.9" not in dumped
        assert "DEADBEEF1234" not in dumped

    def test_comments_are_ignored(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["# SocksPort 9050", "  # a comment", ""])
        config = parse_tor_config(root)
        assert config.socks_port_configured is None


# ---------------------------------------------------------------------------
# Tor config mutation operators (+Option/append, /Option/clear) and
# wildcard %include (S6RM, Section 2-40)
# ---------------------------------------------------------------------------


class TestTorConfigOperators:
    def test_plain_option_parsed_as_set(self):
        assert _parse_directive_line("SocksPort 9050") == ("set", "SocksPort", "9050")

    def test_plus_option_parsed_as_append(self):
        assert _parse_directive_line("+SocksPort 9150") == ("append", "SocksPort", "9150")

    def test_slash_option_parsed_as_clear(self):
        assert _parse_directive_line("/SocksPort") == ("clear", "SocksPort", None)

    # --- SocksPort matrix (Section 32) ------------------------------------

    def test_socksport_plain_set_is_true(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["SocksPort 9050"]))
        assert config.socks_port_configured is True

    def test_socksport_set_then_clear_is_false(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["SocksPort 9050", "/SocksPort"]))
        assert config.socks_port_configured is False

    def test_socksport_set_clear_append_is_true(self, tmp_path):
        config = parse_tor_config(
            _root_with_torrc(tmp_path, ["SocksPort 9050", "/SocksPort", "+SocksPort 9150"])
        )
        assert config.socks_port_configured is True

    def test_socksport_zero_then_append_is_true(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["SocksPort 0", "+SocksPort 9050"]))
        assert config.socks_port_configured is True

    def test_socksport_clear_alone_is_false(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["/SocksPort"]))
        assert config.socks_port_configured is False

    def test_socksport_absent_is_none(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["ControlPort 9051"]))
        assert config.socks_port_configured is None

    def test_socksport_append_alone_is_true(self, tmp_path):
        # Section 9: real Tor appends to the (non-empty) compiled-in
        # default or to an empty set - either way the appended value
        # itself makes the effective set non-empty, so this is a
        # definite True, never a guessed/unsafe value.
        config = parse_tor_config(_root_with_torrc(tmp_path, ["+SocksPort 9050"]))
        assert config.socks_port_configured is True

    # --- ControlPort (Section 28/33) --------------------------------------

    def test_controlport_set_then_clear_is_false(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["ControlPort 9051", "/ControlPort"]))
        assert config.control_port_configured is False

    def test_controlport_clear_then_append_is_true(self, tmp_path):
        config = parse_tor_config(
            _root_with_torrc(tmp_path, ["/ControlPort", "+ControlPort 9051"])
        )
        assert config.control_port_configured is True

    # --- DNSPort / TransPort (Section 29/34/35) ---------------------------

    def test_dnsport_set_then_clear_is_false(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["DNSPort 5353", "/DNSPort"]))
        assert config.dns_port_configured is False

    def test_transport_set_then_clear_is_false(self, tmp_path):
        config = parse_tor_config(_root_with_torrc(tmp_path, ["TransPort 9040", "/TransPort"]))
        assert config.trans_port_configured is False

    # --- Scalar CookieAuthentication (Section 12) --------------------------

    def test_cookie_authentication_clear_is_unknown_not_false(self, tmp_path):
        # Section 12: a scalar's "clear" reverts to Tor's own compiled
        # default, which Serein does not hardcode as a specific boolean.
        config = parse_tor_config(
            _root_with_torrc(tmp_path, ["CookieAuthentication 1", "/CookieAuthentication"])
        )
        assert config.cookie_authentication_configured is None

    # --- %include wildcard support (Section 13-14/36) ----------------------

    def test_include_wildcard_matches_files(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={"10-socks.conf": "SocksPort 9050\n", "ignored.txt": "SocksPort 9999\n"},
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is True

    def test_include_wildcard_ignores_non_matching_files(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={"10-notes.txt": "SocksPort 9999\n"},
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is None

    def test_include_wildcard_question_mark(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/1?.conf"],
            torrc_d={"10.conf": "SocksPort 9050\n", "100.conf": "SocksPort 9999\n"},
        )
        config = parse_tor_config(root)
        # "1?.conf" matches "10.conf" (exactly one char after "1") but
        # not "100.conf" (two chars) - only the matching file is read.
        assert config.socks_port_configured is True

    def test_include_wildcard_lexical_order_clear_wins(self, tmp_path):
        # Section 37: 10-first.conf sets SocksPort, 20-clear.conf clears
        # it - lexical order means the clear applies last -> False.
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={"10-first.conf": "SocksPort 9050\n", "20-clear.conf": "/SocksPort\n"},
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is False

    def test_include_wildcard_lexical_order_enable_wins(self, tmp_path):
        # Reversed filenames so the clear applies first, then the
        # append re-enables it -> True. Directly proves lexical, not
        # arbitrary, ordering.
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={"10-clear.conf": "/SocksPort\n", "20-enable.conf": "+SocksPort 9050\n"},
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is True

    def test_include_wildcard_position_preserved(self, tmp_path):
        root = _root_with_torrc(
            tmp_path,
            ["SocksPort 9050", "%include /etc/tor/torrc.d/*.conf", "/SocksPort"],
            torrc_d={"10-noop.conf": "ControlPort 9051\n"},
        )
        config = parse_tor_config(root)
        # The post-include "/SocksPort" line must still apply after the
        # included content, proving the include is spliced at its exact
        # position, not appended at the end.
        assert config.socks_port_configured is False
        assert config.control_port_configured is True

    def test_include_wildcard_stays_under_injected_root(self, tmp_path):
        # Section 15/36: an absolute-looking wildcard path is re-rooted
        # under the injected root, never the real host /etc/tor/torrc.d.
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={"10-socks.conf": "SocksPort 9050\n"},
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is True
        # A sibling directory outside `root` with a matching filename
        # must never be read even if it happens to exist.
        outside = tmp_path / "etc" / "tor" / "torrc.d"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "10-socks.conf").write_text("SocksPort 7777\n", encoding="utf-8")
        config_again = parse_tor_config(root)
        assert config_again.socks_port_configured is True  # unaffected by the sibling

    def test_root_escape_via_relative_traversal_is_blocked(self, tmp_path):
        # Section 16/38: a sentinel secret placed OUTSIDE root must
        # never be read via ../ traversal in a %include argument.
        sentinel_dir = tmp_path / "outside-root-secret"
        sentinel_dir.mkdir(parents=True, exist_ok=True)
        (sentinel_dir / "passwd").write_text("root:SUPERSECRETVALUE:0:0\n", encoding="utf-8")
        root = _root_with_torrc(
            tmp_path, ["%include ../../../../../../outside-root-secret/passwd"]
        )
        config = parse_tor_config(root)
        dumped = json.dumps(asdict(config))
        assert "SUPERSECRETVALUE" not in dumped
        assert "root:" not in dumped

    def test_root_escape_via_absolute_traversal_is_blocked(self, tmp_path):
        sentinel_dir = tmp_path / "outside-root-secret"
        sentinel_dir.mkdir(parents=True, exist_ok=True)
        (sentinel_dir / "passwd").write_text("root:SUPERSECRETVALUE2:0:0\n", encoding="utf-8")
        root = _root_with_torrc(
            tmp_path, ["%include /../../../../../../outside-root-secret/passwd"]
        )
        config = parse_tor_config(root)
        dumped = json.dumps(asdict(config))
        assert "SUPERSECRETVALUE2" not in dumped

    def test_root_escape_via_wildcard_traversal_is_blocked(self, tmp_path):
        sentinel_dir = tmp_path / "outside-root-secret"
        sentinel_dir.mkdir(parents=True, exist_ok=True)
        (sentinel_dir / "passwd.conf").write_text(
            "SocksPort 9050\n# SUPERSECRETVALUE3\n", encoding="utf-8"
        )
        root = _root_with_torrc(
            tmp_path, ["%include ../../../../../../outside-root-secret/*.conf"]
        )
        config = parse_tor_config(root)
        dumped = json.dumps(asdict(config))
        assert "SUPERSECRETVALUE3" not in dumped
        # Since the traversal is blocked, the include contributes
        # nothing - SocksPort must stay unmentioned, never guessed True.
        assert config.socks_port_configured is None

    def test_include_cycle_with_glob_does_not_recurse_forever(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={"10-self.conf": "%include /etc/tor/torrc\nSocksPort 9050\n"},
        )
        config = parse_tor_config(root)
        assert config.socks_port_configured is True

    def test_wildcard_never_leaks_secrets(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["%include /etc/tor/torrc.d/*.conf"],
            torrc_d={
                "10-bridge.conf": "Bridge obfs4 198.51.100.7:443 CAFEBABE99887766\n",
                "20-cookie.conf": "HashedControlPassword 16:FEEDFACE00112233\n",
            },
        )
        config = parse_tor_config(root)
        assert config.bridge_lines_present is True
        dumped = json.dumps(asdict(config))
        assert "198.51.100.7" not in dumped
        assert "CAFEBABE99887766" not in dumped
        assert "FEEDFACE00112233" not in dumped


# ---------------------------------------------------------------------------
# Tor usability evidence (S6R Corrective C, Section 19-27, 53)
# ---------------------------------------------------------------------------


class TestTorUsability:
    def test_configured_endpoint_alone_without_listener_is_unknown(self, tmp_path):
        root = _add_empty_proc_net(_root_with_torrc(tmp_path, ["SocksPort 9050"]))
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.config.socks_port_configured is True
        assert status.socks_listener_detected is False
        assert status.usable is None

    def test_matching_listener_is_usable_true(self, tmp_path):
        root = _add_listener(_root_with_torrc(tmp_path, ["SocksPort 9050"]), 9050)
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.socks_listener_detected is True
        assert status.usable is True
        assert status.confidence == "medium"

    def test_runtime_active_no_directive_listener_present_is_usable(self, tmp_path):
        root = _add_listener(_empty_root(tmp_path), 9050)
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.config.socks_port_configured is None
        assert status.socks_listener_detected is True
        assert status.usable is True

    def test_explicit_socks_disablement_is_false_even_with_runtime_active(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 0"])
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.usable is False
        assert status.confidence == "high"

    def test_runtime_inactive_with_listener_marker_is_false(self, tmp_path):
        root = _add_listener(_empty_root(tmp_path), 9050)
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor@default.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor@default.service"): CommandResult(3, "inactive", ""),
        })
        status = detect_tor_status(runner=runner, root=root)
        assert status.socks_listener_detected is True
        assert status.service.runtime_unit_active is False
        assert status.usable is False

    def test_runtime_unknown_is_unknown(self, tmp_path):
        root = _add_listener(_empty_root(tmp_path), 9050)
        runner = FakeCommandRunner({"tor": _ok("Tor version 0.4.9.11.")})
        status = detect_tor_status(runner=runner, root=root)
        assert status.service.runtime_unit_present is None
        assert status.usable is None

    def test_custom_socks_port_without_listener_match_stays_unknown(self, tmp_path):
        # Section 22-23: a non-default SocksPort (e.g. 9150) is not
        # detected by the fixed-port-9050 listener check - must never
        # be promoted to usable=True from configuration alone.
        root = _add_empty_proc_net(_root_with_torrc(tmp_path, ["SocksPort 9150"]))
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.usable is None

    def test_explicit_clear_overrides_stale_listener_evidence(self, tmp_path):
        # S6RM Section 26/40 - the security-relevant regression: runtime
        # active + a real listener on 9050 + torrc that explicitly
        # clears SocksPort must NOT report usable=True. Explicit
        # config disablement takes precedence over listener evidence.
        root = _add_listener(
            _root_with_torrc(tmp_path, ["SocksPort 9050", "/SocksPort"]), 9050
        )
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.config.socks_port_configured is False
        assert status.socks_listener_detected is True
        assert status.usable is False

    def test_clear_then_reenable_with_listener_is_usable(self, tmp_path):
        # Section 27: a clear followed by a genuine re-enable, backed by
        # real runtime+listener evidence, is legitimately usable=True.
        root = _add_listener(
            _root_with_torrc(tmp_path, ["SocksPort 9050", "/SocksPort", "+SocksPort 9050"]), 9050
        )
        runner = _runtime_active_runner()
        status = detect_tor_status(runner=runner, root=root)
        assert status.config.socks_port_configured is True
        assert status.usable is True


# ---------------------------------------------------------------------------
# Tor Browser / ordinary browser (Section 17-19, 96, 105)
# ---------------------------------------------------------------------------


class TestTorBrowser:
    def test_absent(self):
        status = detect_tor_browser_status(runner=FakeCommandRunner({}))
        assert status.launcher_installed is False
        assert status.usable is None

    def test_detected(self):
        runner = FakeCommandRunner({"torbrowser-launcher": _ok("0.3.9")})
        status = detect_tor_browser_status(runner=runner)
        assert status.launcher_installed is True
        assert status.usable is None  # presence never implies usable

    def test_detected_via_dpkg_fallback(self):
        runner = FakeCommandRunner({
            ("dpkg-query", "-W", "-f=${Status}", "torbrowser-launcher"): _ok(
                "install ok installed"
            ),
        })
        status = detect_tor_browser_status(runner=runner)
        assert status.launcher_installed is True

    def test_never_treated_as_equivalent_to_firefox_plus_socks(self):
        # Section 105: an ordinary browser's presence must never be
        # folded into Tor Browser's own status.
        status = detect_ordinary_browser_status(
            runner=FakeCommandRunner({"firefox": _ok("Firefox 130.0")})
        )
        tor_browser = detect_tor_browser_status(runner=FakeCommandRunner({}))
        assert status.firefox.installed is True
        assert tor_browser.launcher_installed is False


class TestOrdinaryBrowser:
    def test_isolated_profile_never_available_from_ordinary_browser_alone(self):
        status = detect_ordinary_browser_status(
            runner=FakeCommandRunner({
                "firefox": _ok("Firefox 130.0"), "chromium-browser": _ok("Chromium 128.0"),
            })
        )
        assert status.firefox.installed is True
        assert status.chromium.installed is True
        # OrdinaryBrowserStatus has no isolation/usable field at all -
        # its presence can never be read as "isolated profile ready".
        assert not hasattr(status, "usable")


# ---------------------------------------------------------------------------
# DNS leak model (Section 12, 97)
# ---------------------------------------------------------------------------


class TestDns:
    def test_tor_not_usable_means_no_dns_claim(self):
        tor = TorStatusInfo(usable=False)
        dns = evaluate_dns_privacy(tor)
        assert dns.dns_isolation_proven is None
        assert dns.system_dns_unchanged is True

    def test_tor_unknown_means_no_dns_claim(self):
        tor = TorStatusInfo(usable=None)
        dns = evaluate_dns_privacy(tor)
        assert dns.dns_isolation_proven is None

    def test_tor_usable_still_never_proves_dns_isolation(self):
        # Section 12: "Tor active -> DNS safe" is invalid.
        tor = TorStatusInfo(usable=True)
        dns = evaluate_dns_privacy(tor)
        assert dns.dns_isolation_proven is None
        assert "socks5h" in dns.reason.lower() or "tor browser" in dns.reason.lower()

    def test_system_dns_never_mutated_marker_always_true(self):
        for usable in (True, False, None):
            dns = evaluate_dns_privacy(TorStatusInfo(usable=usable))
            assert dns.system_dns_unchanged is True


# ---------------------------------------------------------------------------
# Kill switch (Section 23-24, 58)
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_never_configured_never_usable(self):
        status = evaluate_kill_switch()
        assert status.configured is False
        assert status.usable is None
        assert status.available is True


# ---------------------------------------------------------------------------
# Private workspace readiness (Section 55-58, 98)
# ---------------------------------------------------------------------------


class TestWorkspace:
    def test_tor_absent_yields_privacy_level_none(self):
        readiness = evaluate_workspace_readiness(
            TorStatusInfo(usable=False), detect_tor_browser_status(FakeCommandRunner({})), False
        )
        assert readiness.privacy_level == "none"
        assert readiness.usable is False

    def test_tor_present_but_workspace_isolation_absent(self):
        readiness = evaluate_workspace_readiness(
            TorStatusInfo(usable=True), detect_tor_browser_status(FakeCommandRunner({})), False
        )
        assert readiness.configured is False
        assert readiness.usable is None
        assert readiness.privacy_level == "tor_application"

    def test_tor_plus_candidate_workspace_never_reports_usable_true(self):
        readiness = evaluate_workspace_readiness(
            TorStatusInfo(usable=True),
            detect_tor_browser_status(FakeCommandRunner({"torbrowser-launcher": _ok("0.3.9")})),
            False,
        )
        assert readiness.usable is not True
        assert readiness.candidate is True

    def test_kill_switch_absent_is_not_configured(self):
        status = evaluate_kill_switch()
        assert status.configured is False

    def test_kill_switch_usable_unknown_never_true(self):
        status = evaluate_kill_switch()
        assert status.usable is not True

    def test_tor_unknown_state_never_reports_workspace_usable(self):
        readiness = evaluate_workspace_readiness(
            TorStatusInfo(usable=None), detect_tor_browser_status(FakeCommandRunner({})), False
        )
        assert readiness.usable is None
        assert readiness.privacy_level == "none"


# ---------------------------------------------------------------------------
# Whonix (Section 25-34, 99-100)
# ---------------------------------------------------------------------------


class TestWhonix:
    def test_vm_backend_unavailable(self, tmp_path):
        root = _empty_root(tmp_path)
        home = _empty_home(tmp_path)
        whonix = detect_whonix_status(runner=FakeCommandRunner({}), root=root, home=home)
        assert whonix.vm_readiness.status == "blocked_no_hardware"
        assert whonix.usable is False
        assert whonix.confidence == "high"

    def test_vm_backend_partial(self, tmp_path):
        root = _kvm_ready_root(tmp_path, module_loaded=False)
        home = _empty_home(tmp_path)
        whonix = detect_whonix_status(runner=FakeCommandRunner({}), root=root, home=home)
        assert whonix.vm_readiness.status == "blocked_module_missing"
        assert whonix.usable is False

    def test_vm_backend_ready_no_images(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _empty_home(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.vm_readiness.status == "ready"
        assert whonix.gateway_image_present is False
        assert whonix.workstation_image_present is False
        assert whonix.usable is False

    def test_only_gateway_present(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=False)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.gateway_image_present is True
        assert whonix.workstation_image_present is False
        assert whonix.usable is False

    def test_only_workstation_present(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=False, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.gateway_image_present is False
        assert whonix.workstation_image_present is True
        assert whonix.usable is False

    def test_both_images_present_topology_unproven(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.gateway_image_present is True
        assert whonix.workstation_image_present is True
        # Section 100/57: never usable=true from presence alone.
        assert whonix.usable is not True
        assert whonix.network_topology_configured is False

    def test_filename_presence_is_never_trusted_as_verified(self, tmp_path, monkeypatch):
        # S6R Corrective D, Section 37: a matching filename must never
        # be treated as a verified artifact.
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.gateway_image_present is True
        assert whonix.gateway_image_verified is None
        assert whonix.workstation_image_present is True
        assert whonix.workstation_image_verified is None
        assert whonix.lifecycle_stage == "present_unverified"

    def test_domain_definition_state_stays_unknown(self, tmp_path, monkeypatch):
        # Section 33: Serein never maps a libvirt domain name to a
        # specific verified artifact - always None, conservative.
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.gateway_domain_defined is None
        assert whonix.workstation_domain_defined is None

    def test_lifecycle_stage_absent_when_no_images(self, tmp_path):
        root = _empty_root(tmp_path)
        home = _empty_home(tmp_path)
        whonix = detect_whonix_status(runner=FakeCommandRunner({}), root=root, home=home)
        assert whonix.lifecycle_stage == "absent"

    def test_lifecycle_stage_is_weaker_of_the_two_artifacts(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=False)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        # Gateway is present_unverified, Workstation is absent - the
        # joint stage must be the weaker ("absent"), not the stronger.
        assert whonix.lifecycle_stage == "absent"

    def test_never_scans_home_directory_wide(self, tmp_path, monkeypatch):
        # Section 29: only the two exact expected filenames are ever
        # checked - a differently-named file must never be detected.
        root = _kvm_ready_root(tmp_path)
        home = _empty_home(tmp_path)
        images_dir = home / ".local" / "share" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / "some-other-whonix-image.qcow2").write_text("", encoding="utf-8")
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        whonix = detect_whonix_status(runner=_ready_vm_runner(), root=root, home=home)
        assert whonix.gateway_image_present is False
        assert whonix.workstation_image_present is False

    def test_never_creates_or_imports_a_vm(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = _ready_vm_runner()
        detect_whonix_status(runner=runner, root=root, home=home)
        for call in runner.calls:
            joined = " ".join(call).lower()
            assert "virsh define" not in joined
            assert "virsh create" not in joined
            assert "virsh start" not in joined


# ---------------------------------------------------------------------------
# Components manifest
# ---------------------------------------------------------------------------


class TestComponents:
    def test_all_component_ids_unique(self):
        components = all_components()
        ids = [c.id for c in components]
        assert len(ids) == len(set(ids))
        assert len(ids) >= 7

    def test_every_component_tier_and_category_recognized(self):
        for component in all_components():
            assert component.recommended_tier in VEIL_TIERS
            assert component.category in VEIL_CATEGORIES

    def test_tor_related_components_are_workspace_tier_not_host(self):
        # Section 1/3: installing tor autostarts a daemon - never a
        # default host-tier install like S5's diagnostic tools.
        workspace_ids = {c.id for c in workspace_components()}
        assert {"tor", "torsocks", "nyx", "obfs4proxy", "tor-browser"} <= workspace_ids

    def test_whonix_components_are_vm_tier(self):
        vm_ids = {c.id for c in vm_components()}
        assert {"whonix-gateway", "whonix-workstation"} <= vm_ids

    def test_whonix_components_have_no_package_never_downloaded(self):
        for component in vm_components():
            assert component.package is None
            assert component.source_type == "user-managed"


# ---------------------------------------------------------------------------
# Capabilities (Section 46, 106)
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_all_ten_ids_present_once(self, tmp_path):
        report = build_veil_capabilities(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        ids = [c.id for c in report.capabilities]
        expected = {
            "tor_client", "tor_socks", "tor_browser", "private_browser_profile",
            "dns_isolation", "tor_only_routing", "kill_switch", "private_workspace",
            "whonix_vm", "vm_privacy_boundary",
        }
        assert set(ids) == expected
        assert len(ids) == len(set(ids))

    def test_to_dict_is_json_serializable(self, tmp_path):
        report = build_veil_capabilities(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        assert json.dumps(report.to_dict())

    def test_tor_package_installed_alone_never_yields_usable_true_anywhere(self, tmp_path):
        # Section 24/106: package presence alone must never imply
        # usable=true for ANY capability, not just tor_client.
        root = _empty_root(tmp_path)
        runner = FakeCommandRunner({"tor": _ok("Tor version 0.4.9.11.")})
        report = build_veil_capabilities(root=root, runner=runner, home=_empty_home(tmp_path))
        for capability in report.capabilities:
            assert capability.usable is not True

    def test_tor_socks_never_proof_of_leak_free_behavior(self, tmp_path):
        runner = FakeCommandRunner({"torsocks": _ok("torsocks 2.5.0")})
        report = build_veil_capabilities(
            root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["tor_socks"].installed is True
        assert by_id["tor_socks"].usable is None

    def test_tor_only_routing_never_usable(self, tmp_path):
        report = build_veil_capabilities(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["tor_only_routing"].usable is None
        assert by_id["tor_only_routing"].installed is False


# ---------------------------------------------------------------------------
# Planner (Section 51-52)
# ---------------------------------------------------------------------------


class TestPlanner:
    def _actions_by_id(self, plan):
        return {a.id: a for a in plan.actions}

    def test_valid_components(self):
        assert VALID_COMPONENTS == ("tor", "workspace", "whonix")

    def test_unknown_component_raises(self, tmp_path):
        with pytest.raises(ValueError):
            build_veil_plan("bogus", root=_empty_root(tmp_path), home=_empty_home(tmp_path))

    def test_tor_package_missing_is_apply(self, tmp_path):
        plan = build_veil_plan(
            "tor", root=_empty_root(tmp_path), runner=FakeCommandRunner({}),
            home=_empty_home(tmp_path),
        )
        actions = self._actions_by_id(plan)
        assert actions["tor.package"].status == "APPLY"

    def test_tor_package_installed_is_noop(self, tmp_path):
        runner = FakeCommandRunner({"tor": _ok("Tor version 0.4.9.11.")})
        plan = build_veil_plan(
            "tor", root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        actions = self._actions_by_id(plan)
        assert actions["tor.package"].status == "NOOP"

    def test_whonix_requested_but_vm_backend_not_ready_is_blocked(self, tmp_path):
        plan = build_veil_plan(
            "whonix", root=_empty_root(tmp_path), runner=FakeCommandRunner({}),
            home=_empty_home(tmp_path),
        )
        actions = self._actions_by_id(plan)
        assert actions["whonix.vm_prerequisites"].status == "BLOCKED"
        assert actions["whonix.gateway_artifact"].status == "BLOCKED"
        assert actions["whonix.gateway_verification"].status == "BLOCKED"
        assert actions["whonix.workstation_artifact"].status == "BLOCKED"
        assert actions["whonix.workstation_verification"].status == "BLOCKED"
        assert actions["whonix.network_topology"].status == "BLOCKED"

    def test_whonix_vm_ready_images_absent_is_apply(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _empty_home(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        plan = build_veil_plan(
            "whonix", root=root, runner=_ready_vm_runner(), home=home
        )
        actions = self._actions_by_id(plan)
        assert actions["whonix.vm_prerequisites"].status == "NOOP"
        assert actions["whonix.gateway_artifact"].status == "APPLY"
        assert actions["whonix.workstation_artifact"].status == "APPLY"
        # Nothing is present yet, so verification has nothing to do -
        # BLOCKED, never APPLY/NOOP (S6R Corrective D, Section 35-36).
        assert actions["whonix.gateway_verification"].status == "BLOCKED"
        assert actions["whonix.workstation_verification"].status == "BLOCKED"
        assert actions["whonix.network_topology"].status == "BLOCKED"

    def test_whonix_images_present_topology_stays_blocked_unverified(self, tmp_path, monkeypatch):
        # S6R Corrective D (defect #4): images present alone must NOT
        # advance the artifact actions to NOOP-then-topology-APPLY -
        # verification/import are never performed, so topology stays
        # BLOCKED even with both images present.
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        plan = build_veil_plan("whonix", root=root, runner=_ready_vm_runner(), home=home)
        actions = self._actions_by_id(plan)
        assert actions["whonix.gateway_artifact"].status == "NOOP"
        assert actions["whonix.workstation_artifact"].status == "NOOP"
        assert actions["whonix.gateway_verification"].status == "BLOCKED"
        assert actions["whonix.workstation_verification"].status == "BLOCKED"
        assert actions["whonix.network_topology"].status == "BLOCKED"

    def test_workspace_component_filter(self, tmp_path):
        plan = build_veil_plan(
            "workspace", root=_empty_root(tmp_path), runner=FakeCommandRunner({}),
            home=_empty_home(tmp_path),
        )
        assert {a.component for a in plan.actions} == {"workspace"}
        ids = {a.id for a in plan.actions}
        assert "workspace.private_profile" in ids
        assert "workspace.routing" in ids
        assert "workspace.kill_switch_policy" in ids

    def test_full_plan_never_executes_a_command_beyond_detection(self, tmp_path):
        runner = FakeCommandRunner({"tor": _ok("Tor version 0.4.9.11.")})
        build_veil_plan(root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path))
        for call in runner.calls:
            joined = " ".join(call).lower()
            assert "install" not in joined
            assert "apt-get" not in joined
            assert not joined.startswith("apt ")


# ---------------------------------------------------------------------------
# Status (Section 47, 91)
# ---------------------------------------------------------------------------


class TestStatus:
    def test_builds_without_error(self, tmp_path):
        status = build_veil_status(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        assert status.schema_version == 1

    def test_to_dict_is_json_serializable_and_leak_free(self, tmp_path):
        root = _root_with_torrc(
            tmp_path, ["Bridge obfs4 203.0.113.5:443 SECRETFINGERPRINT"]
        )
        status = build_veil_status(root=root, home=_empty_home(tmp_path))
        dumped = json.dumps(status.to_dict())
        for forbidden in (
            "203.0.113.5", "SECRETFINGERPRINT", "HashedControlPassword",
        ):
            assert forbidden not in dumped

    def test_no_profile_fields_present(self, tmp_path):
        # Section 90/125: S6 does not register a global boot profile.
        status = build_veil_status(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        assert not hasattr(status, "profile_id")
        assert not hasattr(status, "profile_status")


# ---------------------------------------------------------------------------
# Doctor (Section 48-50, 129)
# ---------------------------------------------------------------------------


class TestDoctor:
    def _by_id(self, report):
        return {c.id: c for c in report.checks}

    def test_clean_system_never_fails(self, tmp_path):
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert all(check.status is not CheckStatus.FAIL for check in report.checks)

    def test_tor_package_without_service_warns(self, tmp_path):
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor.service"): _fail(4, "not-found"),
            ("systemctl", "is-enabled", "tor@default.service"): _fail(4, "not-found"),
        })
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["veil_tor_package_service_mismatch"].status == CheckStatus.WARN

    def test_socks_configured_but_service_inactive_warns(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 9050"])
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor@default.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor@default.service"): CommandResult(3, "inactive", ""),
        })
        report = run_veil_checks(root=root, runner=runner, home=_empty_home(tmp_path))
        by_id = self._by_id(report)
        assert by_id["veil_tor_socks_configured_service_inactive"].status == CheckStatus.WARN

    def test_master_active_runtime_inactive_warns(self, tmp_path):
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            ("systemctl", "is-enabled", "tor.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor.service"): _ok("active"),
            ("systemctl", "is-enabled", "tor@default.service"): _ok("enabled"),
            ("systemctl", "is-active", "tor@default.service"): CommandResult(3, "inactive", ""),
        })
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["veil_tor_package_service_mismatch"].status == CheckStatus.WARN

    def test_tor_only_claim_check_currently_always_passes(self, tmp_path):
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["veil_tor_only_claim_kill_switch"].status == CheckStatus.PASS

    def test_no_hardware_whonix_backend_is_skip_not_fail(self, tmp_path):
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["veil_whonix_backend_readiness"].status == CheckStatus.SKIP

    def test_partial_whonix_images_warns(self, tmp_path, monkeypatch):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=False)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        report = run_veil_checks(root=root, runner=_ready_vm_runner(), home=home)
        by_id = self._by_id(report)
        assert by_id["veil_whonix_images_partial"].status == CheckStatus.WARN

    def test_no_tor_browser_is_skip_not_fail(self, tmp_path):
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["veil_tor_browser_availability"].status == CheckStatus.SKIP

    def test_to_dict_is_json_serializable(self, tmp_path):
        report = run_veil_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert json.dumps(report.to_dict())


# ---------------------------------------------------------------------------
# Cross-cutting invariants (Section 100-107)
# ---------------------------------------------------------------------------


_FORBIDDEN_ACTION_PHRASES = (
    "route all traffic", "global tor routing", "iptables", "nftables", "nft ",
    "resolv.conf", "http_proxy", "https_proxy", "all_proxy",
)


class TestInvariants:
    def test_whonix_workstation_never_planned_with_direct_clearnet_egress(
        self, tmp_path, monkeypatch
    ):
        root = _kvm_ready_root(tmp_path)
        home = _home_with_images(tmp_path, gateway=True, workstation=True)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        plan = build_veil_plan("whonix", root=root, runner=_ready_vm_runner(), home=home)
        topology = next(a for a in plan.actions if a.id == "whonix.network_topology")
        combined = f"{topology.tool} {topology.reason} {topology.target}".lower()
        # The invariant statement itself must be present, and no phrase
        # enabling direct/bridged host-facing egress may appear.
        assert "never" in combined and "clearnet egress" in combined
        assert "bridged" not in combined
        assert "workstation: enabled" not in combined
        assert "direct host network" not in combined

    def test_default_plan_never_enables_global_tor_routing(self, tmp_path):
        plan = build_veil_plan(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        for action in plan.actions:
            combined = " ".join(
                str(v) for v in (action.tool, action.reason, action.target, action.current) if v
            ).lower()
            assert "route all traffic" not in combined
            assert "global tor routing" not in combined

    def test_default_plan_never_replaces_global_dns(self, tmp_path):
        plan = build_veil_plan(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        for action in plan.actions:
            combined = " ".join(
                str(v) for v in (action.tool, action.reason, action.target, action.current) if v
            ).lower()
            assert "resolv.conf" not in combined
            assert "/etc/resolv.conf" not in combined

    def test_plan_never_mutates_firewall(self, tmp_path):
        plan = build_veil_plan(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        for action in plan.actions:
            if action.status != "APPLY":
                continue
            combined = f"{action.action} {action.tool}".lower()
            assert "iptables" not in combined
            assert "nftables" not in combined
            assert "ufw" not in combined
            assert "firewalld" not in combined

    def test_plan_never_sets_global_proxy_env(self, tmp_path):
        plan = build_veil_plan(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        for action in plan.actions:
            combined = " ".join(
                str(v) for v in (action.tool, action.reason, action.target) if v
            ).lower()
            assert "http_proxy" not in combined
            assert "https_proxy" not in combined
            assert "all_proxy" not in combined

    def test_tor_browser_never_equated_with_firefox_plus_socks(self, tmp_path):
        report = build_veil_capabilities(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["tor_browser"].mechanism is not None
        assert "firefox" not in by_id["tor_browser"].mechanism.lower()

    def test_tor_browser_launcher_never_claims_to_be_official_release(self, tmp_path):
        # S6R Corrective E, Section 42: the launcher package itself must
        # never be described as *being* an official Tor Project release.
        report = build_veil_capabilities(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        by_id = {c.id: c for c in report.capabilities}
        mechanism = by_id["tor_browser"].mechanism.lower()
        assert "official tor project release" not in mechanism

    def test_privacy_levels_are_mechanism_names_not_marketing_confidence(self):
        for level in PRIVACY_LEVELS:
            assert "anonymity" not in level
            assert "low" not in level
            assert "high" not in level

    def test_no_capability_reports_strong_privacy_usable_true_from_installation_alone(
        self, tmp_path
    ):
        # Section 106: even with every optional tool "installed" via a
        # fake runner, workspace/whonix/tor_only/kill_switch must never
        # report usable=true, since none of the real underlying
        # evidence (active service + real routing + real topology) is
        # present.
        runner = FakeCommandRunner({
            "tor": _ok("Tor version 0.4.9.11."),
            "torsocks": _ok("torsocks 2.5.0"),
            "torbrowser-launcher": _ok("0.3.9"),
        })
        report = build_veil_capabilities(
            root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        by_id = {c.id: c for c in report.capabilities}
        for capability_id in (
            "private_workspace", "whonix_vm", "tor_only_routing", "kill_switch",
        ):
            assert by_id[capability_id].usable is not True


# ---------------------------------------------------------------------------
# No external-network / no leak / no mutation regressions (Section 91-93,
# 116-118)
# ---------------------------------------------------------------------------


_FORBIDDEN_NETWORK_MARKERS = (
    "check.torproject.org", "ipify", "ifconfig.me", "icanhazip", ".onion",
)


class TestNoExternalNetworkOrLeaks:
    def test_plan_verification_fields_never_reference_external_services(self, tmp_path):
        plan = build_veil_plan(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        for action in plan.actions:
            lowered = action.verification.lower()
            for marker in _FORBIDDEN_NETWORK_MARKERS:
                assert marker not in lowered

    def test_capabilities_never_reference_external_services(self, tmp_path):
        report = build_veil_capabilities(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        dumped = json.dumps(report.to_dict()).lower()
        for marker in _FORBIDDEN_NETWORK_MARKERS:
            assert marker not in dumped

    def test_status_never_leaks_identity_fields(self, tmp_path):
        status = build_veil_status(root=_empty_root(tmp_path), home=_empty_home(tmp_path))
        dumped = json.dumps(status.to_dict())
        for forbidden_key in (
            '"hostname"', '"username"', '"mac_address"', '"ssid"', '"public_ip"',
            '"vpn"', '"circuit"', '"entry_guard"', '"exit_relay"',
        ):
            assert forbidden_key not in dumped

    def test_full_workflow_never_issues_a_mutating_or_network_command(self, tmp_path):
        root = _root_with_torrc(tmp_path, ["SocksPort 9050"])
        home = _empty_home(tmp_path)
        runner = FakeCommandRunner({"tor": _ok("Tor version 0.4.9.11.")})
        build_veil_status(root=root, runner=runner, home=home)
        build_veil_capabilities(root=root, runner=runner, home=home)
        build_veil_plan(root=root, runner=runner, home=home)
        run_veil_checks(root=root, runner=runner, home=home)

        forbidden_argv_markers = (
            "apt-get install", "apt install", "apt-get remove", "apt-get purge",
            "systemctl start", "systemctl enable", "systemctl restart",
            "virsh define", "virsh create",
            "wget", "curl", "iptables", "nft ", "ufw ", "netns add", "podman run",
            "docker run", "distrobox create",
        )
        for call in runner.calls:
            joined = " ".join(call).lower()
            for marker in forbidden_argv_markers:
                assert marker not in joined, f"unexpected mutating/network call: {call}"
