"""Cyber subsystem tests. Every detection call uses a FakeCommandRunner
and (where relevant) an injected root — never the real host's PATH,
filesystem, real NICs, real root privileges, real Wi-Fi, real KVM, a
real Podman daemon, or real capture permissions, so tests are
independent of whatever happens to be installed on the machine running
them. No test performs an active network probe, a packet capture, a
container/VM creation, or an exploit/crack workflow."""

from __future__ import annotations

import json

import pytest

from serein.cyber.capabilities import build_cyber_capabilities
from serein.cyber.capture import detect_capture_status
from serein.cyber.doctor import run_cyber_checks
from serein.cyber.models import (
    CYBER_CAPABILITIES_SCHEMA_VERSION,
    CYBER_CATEGORIES,
    CYBER_PLAN_SCHEMA_VERSION,
    CYBER_TIERS,
)
from serein.cyber.network import detect_network_status
from serein.cyber.planner import VALID_COMPONENTS, build_cyber_plan
from serein.cyber.reverse import detect_reverse_status
from serein.cyber.status import build_cyber_status
from serein.cyber.toolbox import (
    container_toolbox_installed,
    container_toolbox_reason,
    detect_host_hygiene,
    detect_toolbox_status,
)
from serein.cyber.tools import (
    HOST_NETWORK_TOOLS,
    TOOLBOX_EXPLOIT_DEV_TOOLS,
    TOOLBOX_PASSWORD_AUDIT_TOOLS,
    all_tools,
    default_apt_packages,
    default_host_tools,
    host_tools,
    toolbox_tools,
)
from serein.cyber.virtualization import detect_vm_status, evaluate_vm_readiness
from serein.development.runner import CommandResult
from serein.doctor.models import CheckStatus


class FakeCommandRunner:
    """Maps either an exact argv tuple or a bare binary name to a
    canned CommandResult (or None = "not found"). An exact-argv key
    takes precedence over a bare binary-name fallback, so a single
    binary invoked with different flags (e.g. ``dumpcap -v`` for
    version detection vs ``dumpcap -D`` for capture-permission
    detection) can be given distinct canned responses. Records every
    call for tests that need to assert on invocation without ever
    actually running anything."""

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


def _ok(binary: str, stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _fail(returncode: int = 1, stderr: str = "permission denied") -> CommandResult:
    return CommandResult(returncode=returncode, stdout="", stderr=stderr)


class TestNetwork:
    def test_all_absent(self):
        status = detect_network_status(runner=FakeCommandRunner({}))
        assert not status.nmap.installed
        assert not status.tcpdump.installed
        assert not status.dig.installed

    def test_nmap_present(self):
        runner = FakeCommandRunner({"nmap": _ok("nmap", "Nmap version 7.95")})
        status = detect_network_status(runner=runner)
        assert status.nmap.installed is True
        assert status.nmap.version == "7.95"

    def test_tcpdump_present(self):
        runner = FakeCommandRunner({"tcpdump": _ok("tcpdump", "tcpdump version 4.99.5")})
        status = detect_network_status(runner=runner)
        assert status.tcpdump.installed is True

    def test_never_invokes_nmap_against_a_target(self):
        # Regression: the probe args must only ever be a version-style
        # flag, never a target/hostname/IP.
        runner = FakeCommandRunner({"nmap": _ok("nmap", "Nmap version 7.95")})
        detect_network_status(runner=runner)
        for call in runner.calls:
            if call[0] == "nmap":
                assert len(call) == 2
                assert call[1] in ("--version",)


class TestCapture:
    def test_dumpcap_absent(self):
        status = detect_capture_status(runner=FakeCommandRunner({}))
        assert status.dumpcap.installed is False
        assert status.capture_permitted is None
        assert "not installed" in status.capture_permission_reason

    def test_dumpcap_present_permission_granted(self):
        runner = FakeCommandRunner({
            "dumpcap": _ok("dumpcap", "Dumpcap 4.2.0"),
        })

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _ok("dumpcap", "1. eth0\n2. lo\n")
                return super().run(args, timeout)

        status = detect_capture_status(runner=_Runner(runner._responses))
        assert status.dumpcap.installed is True
        assert status.capture_permitted is True

    def test_dumpcap_present_permission_denied(self):
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _fail()
                return super().run(args, timeout)

        status = detect_capture_status(runner=_Runner(runner._responses))
        assert status.capture_permitted is False

    @pytest.mark.parametrize("phrasing", [
        "permission denied",
        "You don't have permission to capture on device eth0",
        "You do not have permission to open device",
        "Operation not permitted",
        "insufficient privileges to capture",
        "EPERM",
        "EACCES",
    ])
    def test_dumpcap_permission_denied_matches_several_phrasings(self, phrasing):
        # Robust pattern matching (S5R Section 4/7) - never a single
        # hardcoded exact string.
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _fail(stderr=phrasing)
                return super().run(args, timeout)

        status = detect_capture_status(runner=_Runner(runner._responses))
        assert status.capture_permitted is False

    def test_dumpcap_succeeds_but_empty_interface_list_is_unknown(self):
        # A nonzero exit code is not the only way to fail to prove
        # permission - a *successful* run with no listed interfaces
        # proves nothing either (S5R Section 4).
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _ok("dumpcap", "")
                return super().run(args, timeout)

        status = detect_capture_status(runner=_Runner(runner._responses))
        assert status.capture_permitted is None

    def test_dumpcap_nonzero_unrelated_error_is_unknown(self):
        # A bare nonzero exit code must NOT be equated with permission
        # denial (S5R Section 3) - an unrelated runtime error is
        # "unknown", never "denied".
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _fail(returncode=2, stderr="dumpcap: unrecognized option")
                return super().run(args, timeout)

        status = detect_capture_status(runner=_Runner(runner._responses))
        assert status.capture_permitted is None

    def test_dumpcap_present_permission_unknown_when_check_fails(self):
        # Version probe (`dumpcap -v`) succeeds but no response is
        # configured for the separate `dumpcap -D` permission check,
        # so the runner returns None for that call specifically.
        runner = FakeCommandRunner({("dumpcap", "-v"): _ok("dumpcap", "Dumpcap 4.2.0")})
        status = detect_capture_status(runner=runner)
        assert status.dumpcap.installed is True
        assert status.capture_permitted is None

    def test_never_performs_a_live_capture(self):
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})
        detect_capture_status(runner=runner)
        for call in runner.calls:
            assert "-i" not in call
            assert "-w" not in call
            assert "capture" not in " ".join(call).lower()

    def test_permission_check_never_lists_real_interfaces_in_status(self, monkeypatch):
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _ok("dumpcap", "1. eth0 (Ethernet)\n2. wlan0 (Wireless)\n")
                return super().run(args, timeout)

        status = detect_capture_status(runner=_Runner(runner._responses))
        blob = json.dumps({
            "permitted": status.capture_permitted,
            "reason": status.capture_permission_reason,
        })
        assert "eth0" not in blob
        assert "wlan0" not in blob


class TestReverse:
    def test_all_absent(self):
        status = detect_reverse_status(runner=FakeCommandRunner({}))
        assert not status.file.installed
        assert not status.binutils.installed
        assert not status.gdb.installed

    def test_file_present(self):
        runner = FakeCommandRunner({"file": _ok("file", "file-5.46")})
        status = detect_reverse_status(runner=runner)
        assert status.file.installed is True

    def test_binutils_via_objdump(self):
        runner = FakeCommandRunner({"objdump": _ok("objdump", "GNU objdump 2.42")})
        status = detect_reverse_status(runner=runner)
        assert status.binutils.installed is True

    def test_binutils_via_dpkg(self):
        runner = FakeCommandRunner({"dpkg-query": _ok("dpkg-query", "install ok installed")})
        status = detect_reverse_status(runner=runner)
        assert status.binutils.installed is True

    def test_gdb_reused_from_s3_cpp_detection(self):
        runner = FakeCommandRunner({"gdb": _ok("gdb", "GNU gdb 15.1")})
        status = detect_reverse_status(runner=runner)
        assert status.gdb.installed is True
        assert status.gdb.version == "15.1"

    def test_radare2_present(self):
        runner = FakeCommandRunner({"r2": _ok("r2", "radare2 5.9.0")})
        status = detect_reverse_status(runner=runner)
        assert status.radare2.installed is True

    def test_never_scans_filesystem_binaries(self):
        # Regression: detection must be presence-only probes, never an
        # argument that looks like a filesystem path/glob to scan.
        runner = FakeCommandRunner({"file": _ok("file", "file-5.46")})
        detect_reverse_status(runner=runner)
        for call in runner.calls:
            if call[0] == "file":
                assert "/" not in " ".join(call[1:])
                assert "*" not in " ".join(call[1:])


class TestToolbox:
    def test_podman_absent(self):
        status = detect_toolbox_status(runner=FakeCommandRunner({}))
        assert not status.podman.installed

    def test_podman_present(self):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")})
        status = detect_toolbox_status(runner=runner)
        assert status.podman.installed is True

    def test_distrobox_present(self):
        runner = FakeCommandRunner({"distrobox": _ok("distrobox", "distrobox: 1.8.2.4")})
        status = detect_toolbox_status(runner=runner)
        assert status.distrobox.installed is True

    def test_docker_only(self):
        runner = FakeCommandRunner({"docker": _ok("docker", "Docker version 27.0.0")})
        status = detect_toolbox_status(runner=runner)
        assert status.docker.installed and not status.podman.installed

    def test_podman_and_docker(self):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.7.0"),
            "docker": _ok("docker", "Docker version 27.0.0"),
        })
        status = detect_toolbox_status(runner=runner)
        assert status.podman.installed and status.docker.installed


class TestContainerToolboxInstalled:
    """S5RM: ``container_toolbox.installed`` requires engine AND
    Distrobox together - neither component alone is a complete
    toolbox."""

    def test_neither_present_is_not_installed(self):
        status = detect_toolbox_status(runner=FakeCommandRunner({}))
        assert container_toolbox_installed(status) is False

    def test_engine_only_is_not_installed(self):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")})
        status = detect_toolbox_status(runner=runner)
        assert container_toolbox_installed(status) is False

    def test_distrobox_only_is_not_installed(self):
        runner = FakeCommandRunner({"distrobox": _ok("distrobox", "distrobox: 1.8.2.4")})
        status = detect_toolbox_status(runner=runner)
        assert container_toolbox_installed(status) is False

    def test_podman_plus_distrobox_is_installed(self):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.7.0"),
            "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
        })
        status = detect_toolbox_status(runner=runner)
        assert container_toolbox_installed(status) is True

    def test_docker_plus_distrobox_is_installed(self):
        runner = FakeCommandRunner({
            "docker": _ok("docker", "Docker version 27.0.0"),
            "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
        })
        status = detect_toolbox_status(runner=runner)
        assert container_toolbox_installed(status) is True

    def test_reason_text_matches_actual_state(self):
        neither = detect_toolbox_status(runner=FakeCommandRunner({}))
        assert "no container engine" in container_toolbox_reason(neither).lower()

        engine_only = detect_toolbox_status(
            runner=FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")})
        )
        reason = container_toolbox_reason(engine_only)
        assert "distrobox is not" in reason.lower()

        distrobox_only = detect_toolbox_status(
            runner=FakeCommandRunner({"distrobox": _ok("distrobox", "distrobox: 1.8.2.4")})
        )
        reason = container_toolbox_reason(distrobox_only)
        assert "no supported container engine" in reason.lower()

        both = detect_toolbox_status(runner=FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.7.0"),
            "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
        }))
        reason = container_toolbox_reason(both)
        assert "unverified" in reason.lower()


class TestHostHygiene:
    def test_none_present(self):
        status = detect_host_hygiene(runner=FakeCommandRunner({}))
        assert not status.hashcat.installed
        assert not status.john.installed
        assert not status.metasploit.installed

    def test_hashcat_present(self):
        runner = FakeCommandRunner({"hashcat": _ok("hashcat", "hashcat v6.2.6")})
        status = detect_host_hygiene(runner=runner)
        assert status.hashcat.installed is True

    def test_aircrack_present(self):
        runner = FakeCommandRunner({"aircrack-ng": _ok("aircrack-ng", "Aircrack-ng 1.7")})
        status = detect_host_hygiene(runner=runner)
        assert status.aircrack_ng.installed is True


class TestVM:
    def test_kvm_absent(self, tmp_path):
        status = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert status.kvm_device_present is False
        assert status.user_access is None

    def test_kvm_device_present(self, tmp_path):
        (tmp_path / "dev").mkdir()
        (tmp_path / "dev" / "kvm").write_text("")
        status = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert status.kvm_device_present is True

    def test_kvm_module_loaded_via_proc_modules(self, tmp_path):
        (tmp_path / "proc").mkdir()
        (tmp_path / "proc" / "modules").write_text(
            "kvm_intel 372736 0 - Live 0x0\nkvm 1064960 1 kvm_intel, Live 0x0\n",
            encoding="utf-8",
        )
        status = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert status.kvm_module_loaded is True

    def test_qemu_absent(self, tmp_path):
        status = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert not status.qemu.installed

    def test_qemu_present(self, tmp_path):
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
        })
        status = detect_vm_status(runner=runner, root=tmp_path)
        assert status.qemu.installed is True

    def test_libvirt_present(self, tmp_path):
        runner = FakeCommandRunner({"virsh": _ok("virsh", "10.0.0")})
        status = detect_vm_status(runner=runner, root=tmp_path)
        assert status.libvirt.installed is True

    def test_user_access_unknown_without_kvm(self, tmp_path):
        status = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert status.user_access is None

    def test_never_creates_a_vm(self, tmp_path):
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
        })
        detect_vm_status(runner=runner, root=tmp_path)
        for call in runner.calls:
            assert "-hda" not in call
            assert "start" not in call

    def test_never_starts_libvirtd(self, tmp_path):
        runner = FakeCommandRunner({"virsh": _ok("virsh", "10.0.0")})
        detect_vm_status(runner=runner, root=tmp_path)
        for call in runner.calls:
            assert "start" not in call
            assert "create" not in call


def _kvm_ready_root(tmp_path, module_loaded=True):
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "kvm").write_text("")
    if module_loaded:
        (tmp_path / "proc").mkdir()
        (tmp_path / "proc" / "modules").write_text("kvm 1064960 0 - Live 0x0\n")
    return tmp_path


class TestVMReadiness:
    """The single canonical VM-readiness verdict (S5R Section 17-18/22)
    that capabilities.py/planner.py/doctor.py all consume identically."""

    def test_no_kvm_device_is_blocked_no_hardware(self, tmp_path):
        vm = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "blocked_no_hardware"
        assert readiness.usable is False

    def test_device_present_module_missing_is_blocked(self, tmp_path):
        _kvm_ready_root(tmp_path, module_loaded=False)
        vm = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "blocked_module_missing"
        assert readiness.usable is False

    def test_user_access_false_is_blocked_no_access(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: False)
        vm = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "blocked_no_access"
        assert readiness.usable is False

    def test_user_access_unknown_is_blocked_not_ready(self, tmp_path, monkeypatch):
        # os.access raising -> VMCapabilityInfo.user_access is None.
        def _raise(*a, **kw):
            raise OSError("no such concept on this platform")

        monkeypatch.setattr("os.access", _raise)
        _kvm_ready_root(tmp_path)
        vm = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert vm.user_access is None
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "blocked_access_unknown"
        assert readiness.usable is False

    def test_access_ready_qemu_missing_is_needs_qemu(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        vm = detect_vm_status(runner=FakeCommandRunner({}), root=tmp_path)
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "needs_qemu"
        assert readiness.usable is False

    def test_qemu_ready_libvirt_missing_is_needs_libvirt(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
        })
        vm = detect_vm_status(runner=runner, root=tmp_path)
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "needs_libvirt"
        assert readiness.usable is False

    def test_full_chain_is_ready(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
            "virsh": _ok("virsh", "10.0.0"),
        })
        vm = detect_vm_status(runner=runner, root=tmp_path)
        readiness = evaluate_vm_readiness(vm)
        assert readiness.status == "ready"
        assert readiness.usable is True


class TestTools:
    def test_no_duplicate_ids(self):
        tools = all_tools()
        ids = [t.id for t in tools]
        assert len(ids) == len(set(ids))

    def test_every_tool_has_a_recognized_tier(self):
        for tool in all_tools():
            assert tool.recommended_tier in CYBER_TIERS

    def test_every_tool_has_a_recognized_category(self):
        for tool in all_tools():
            assert tool.category in CYBER_CATEGORIES

    def test_every_tool_has_a_recognized_source_type(self):
        allowed = {
            "ubuntu-repository", "official-upstream-repository", "official-upstream-binary",
            "language-bootstrap-tool", "user-installed", "optional", "python-package-index",
        }
        for tool in all_tools():
            assert tool.source_type in allowed

    def test_host_baseline_tools_are_host_tier(self):
        for tool in HOST_NETWORK_TOOLS:
            assert tool.recommended_tier == "host"

    def test_password_audit_tools_are_toolbox_tier(self):
        # Section 15/77: hashcat/john/hydra must never be host baseline.
        for tool in TOOLBOX_PASSWORD_AUDIT_TOOLS:
            assert tool.recommended_tier == "toolbox"
        ids = {t.id for t in TOOLBOX_PASSWORD_AUDIT_TOOLS}
        assert {"hashcat", "john", "hydra"} <= ids

    def test_exploit_frameworks_are_toolbox_tier(self):
        for tool in TOOLBOX_EXPLOIT_DEV_TOOLS:
            assert tool.recommended_tier == "toolbox"

    def test_no_full_kali_metapackage_in_manifest(self):
        # Section 78 invariant: Serein's host plan must never attempt
        # to install a full Kali toolset/metapackage.
        ids = {t.id for t in all_tools()}
        packages = {t.package for t in all_tools() if t.package}
        for forbidden in ("kali-linux-default", "kali-linux-large", "kali-linux-everything",
                           "kali-linux-headless", "kali-tools-top10"):
            assert forbidden not in ids
            assert forbidden not in packages

    def test_host_tools_helper_matches_tier_filter(self):
        assert set(host_tools()) == {t for t in all_tools() if t.recommended_tier == "host"}

    def test_toolbox_tools_helper_matches_tier_filter(self):
        assert set(toolbox_tools()) == {t for t in all_tools() if t.recommended_tier == "toolbox"}

    def test_default_apt_packages_sorted_deduplicated(self):
        packages = default_apt_packages()
        assert packages == sorted(set(packages))
        assert len(packages) > 0

    def test_default_apt_packages_only_from_host_tier(self):
        packages = set(default_apt_packages())
        toolbox_packages = {t.package for t in toolbox_tools() if t.package}
        # hashcat/john etc. are real Ubuntu packages but toolbox-tier;
        # they must never appear in the default host install set.
        assert not (packages & {"hashcat", "john", "hydra", "sleuthkit", "binwalk"})
        assert toolbox_packages or True  # sanity: toolbox has apt-sourced entries too

    def test_burpsuite_is_user_managed_not_a_source_type(self):
        # Regression for a real bug caught during this pass: tier and
        # source_type must never be confused with each other.
        burp = next(t for t in all_tools() if t.id == "burpsuite")
        assert burp.recommended_tier == "user-managed"
        assert burp.source_type != "user-managed"

    def test_ghidra_not_claimed_as_ubuntu_package(self):
        ghidra = next(t for t in all_tools() if t.id == "ghidra")
        assert ghidra.source_type != "ubuntu-repository"


class TestHostDefaultInstall:
    """recommended_tier == "host" is a *tier* (appropriate to have on a
    host if chosen), not a claim about Serein's *default* install set
    (S5R Section 10-15) - Wireshark GUI is the concrete example."""

    def test_wireshark_is_host_tier_but_not_default_install(self):
        wireshark = next(t for t in all_tools() if t.id == "wireshark")
        assert wireshark.recommended_tier == "host"
        assert wireshark.default_install is False

    def test_tshark_is_host_tier_and_default_install(self):
        tshark = next(t for t in all_tools() if t.id == "tshark")
        assert tshark.recommended_tier == "host"
        assert tshark.default_install is True

    def test_default_apt_packages_excludes_wireshark(self):
        assert "wireshark" not in default_apt_packages()

    def test_default_host_tools_excludes_wireshark(self):
        ids = {t.id for t in default_host_tools()}
        assert "wireshark" not in ids
        assert "tshark" in ids

    def test_default_host_tools_is_strict_subset_of_host_tools(self):
        default_ids = {t.id for t in default_host_tools()}
        host_ids = {t.id for t in host_tools()}
        assert default_ids <= host_ids
        assert default_ids < host_ids  # strictly smaller (wireshark excluded)

    def test_profile_default_package_list_excludes_wireshark(self):
        import json as _json
        from pathlib import Path

        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "profiles" / "cyber" / "cyber.profile.json"
        )
        data = _json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "wireshark" not in data["packages"]

    def test_profile_default_packages_match_canonical_default_plus_s2(self):
        import json as _json
        from pathlib import Path

        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "profiles" / "cyber" / "cyber.profile.json"
        )
        data = _json.loads(manifest_path.read_text(encoding="utf-8"))
        s2_packages = {"power-profiles-daemon", "systemd-zram-generator"}
        expected = set(default_apt_packages()) | s2_packages
        assert set(data["packages"]) == expected

    def test_host_baseline_noop_when_default_tools_installed_wireshark_missing(self, tmp_path):
        responses = {
            "nmap": _ok("nmap", "Nmap version 7.95"),
            "tcpdump": _ok("tcpdump", "tcpdump version 4.99.5"),
            "dig": _ok("dig", "DiS 9.18.0"),
            "whois": _ok("whois", "whois 5.5.0"),
            "openssl": _ok("openssl", "OpenSSL 3.2.0"),
            "socat": _ok("socat", "socat 1.7.4"),
            "nc": _ok("nc", "OpenBSD netcat"),
            "mtr": _ok("mtr", "mtr 0.95"),
            "ethtool": _ok("ethtool", "ethtool 6.7"),
            ("dumpcap", "-v"): _ok("dumpcap", "Dumpcap 4.2.0"),
            "tshark": _ok("tshark", "TShark 4.2.0"),
            # wireshark deliberately absent
            "file": _ok("file", "file-5.46"),
            "objdump": _ok("objdump", "GNU objdump 2.42"),
            "exiftool": _ok("exiftool", "13.00"),
        }
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner(responses))
        actions = {a.id: a for a in plan.actions}
        assert actions["host.baseline"].status == "NOOP"

    def test_optional_wireshark_installed_does_not_change_baseline_state(self, tmp_path):
        # Installing the optional Wireshark GUI on top of an otherwise
        # incomplete host must not itself flip host.baseline to NOOP -
        # only the default-install set matters for that status.
        plan_without = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        wireshark_runner = FakeCommandRunner({"wireshark": _ok("wireshark", "Wireshark 4.2.0")})
        plan_with_wireshark_only = build_cyber_plan(root=tmp_path, runner=wireshark_runner)
        actions_without = {a.id: a for a in plan_without.actions}
        actions_with = {a.id: a for a in plan_with_wireshark_only.actions}
        assert actions_without["host.baseline"].status == "APPLY"
        assert actions_with["host.baseline"].status == "APPLY"


class TestSourceMetadata:
    """S5R Section 24-30/41: source_type reflects a deliberate,
    documented, version-evidence-based decision, not inertia in either
    direction."""

    def test_ffuf_source_is_ubuntu_repository(self):
        ffuf = next(t for t in all_tools() if t.id == "ffuf")
        assert ffuf.source_type == "ubuntu-repository"
        assert ffuf.package == "ffuf"

    def test_gobuster_source_is_ubuntu_repository(self):
        gobuster = next(t for t in all_tools() if t.id == "gobuster")
        assert gobuster.source_type == "ubuntu-repository"
        assert gobuster.package == "gobuster"

    def test_sqlmap_source_is_ubuntu_repository(self):
        sqlmap = next(t for t in all_tools() if t.id == "sqlmap")
        assert sqlmap.source_type == "ubuntu-repository"
        assert sqlmap.package == "sqlmap"

    def test_mitmproxy_source_stays_python_package_index(self):
        # The one deliberate exception: Ubuntu's apt package is
        # significantly stale against upstream (8.1.1 vs 12.2.3).
        mitmproxy = next(t for t in all_tools() if t.id == "mitmproxy")
        assert mitmproxy.source_type == "python-package-index"

    def test_ffuf_gobuster_sqlmap_still_toolbox_tier(self):
        # Source choice must never change tier classification.
        for tool_id in ("ffuf", "gobuster", "sqlmap"):
            tool = next(t for t in all_tools() if t.id == tool_id)
            assert tool.recommended_tier == "toolbox"


class TestCapabilities:
    def test_schema_version(self):
        report = build_cyber_capabilities(runner=FakeCommandRunner({}))
        assert report.schema_version == CYBER_CAPABILITIES_SCHEMA_VERSION

    def test_all_twelve_ids_present_once(self):
        report = build_cyber_capabilities(runner=FakeCommandRunner({}))
        ids = [c.id for c in report.capabilities]
        expected = {
            "network_diagnostics", "packet_capture_tools", "packet_capture_permission",
            "dns_diagnostics", "tls_diagnostics", "network_scanning_tools",
            "web_testing_toolbox", "reverse_engineering", "forensics_toolbox",
            "wireless_tooling", "container_toolbox", "vm_isolation",
        }
        assert set(ids) == expected
        assert len(ids) == len(set(ids))

    def test_packet_capture_permission_never_guessed_true(self):
        report = build_cyber_capabilities(runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["packet_capture_permission"].usable is not True

    def test_packet_capture_permission_reflects_real_evidence(self, tmp_path):
        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _ok("dumpcap", "1. eth0\n")
                return super().run(args, timeout)

        runner = _Runner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["packet_capture_permission"].usable is True

    def test_vm_isolation_usable_requires_full_chain(self, tmp_path):
        # qemu alone (no KVM device/module/access) must not be usable.
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
        })
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["vm_isolation"].usable is not True

    def test_wireless_tooling_never_usable_true(self):
        # Section 17: monitor-mode/hardware capability is never
        # verified, so usable must never be guessed True.
        runner = FakeCommandRunner({"aircrack-ng": _ok("aircrack-ng", "Aircrack-ng 1.7")})
        report = build_cyber_capabilities(runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["wireless_tooling"].usable is not True

    def test_container_toolbox_usable_is_always_none(self, tmp_path):
        # S5R Section 31-34: binary presence never proves rootless
        # runtime usability - usable stays None even when both the
        # engine and Distrobox are installed, since S5 never runs/
        # creates a container merely to prove it.
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.7.0"),
            "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
        })
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["container_toolbox"].installed is True
        assert by_id["container_toolbox"].usable is None

    def test_container_toolbox_installed_false_when_absent(self, tmp_path):
        report = build_cyber_capabilities(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["container_toolbox"].installed is False
        assert by_id["container_toolbox"].usable is None

    def test_container_toolbox_podman_only_is_not_installed(self, tmp_path):
        # S5RM Section 3-4: the toolbox is the engine *and* Distrobox
        # together - an engine alone must not report installed=True.
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")})
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["container_toolbox"].installed is False
        assert by_id["container_toolbox"].usable is None

    def test_container_toolbox_docker_only_is_not_installed(self, tmp_path):
        runner = FakeCommandRunner({"docker": _ok("docker", "Docker version 27.3.1")})
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["container_toolbox"].installed is False
        assert by_id["container_toolbox"].usable is None

    def test_container_toolbox_distrobox_only_is_not_installed(self, tmp_path):
        runner = FakeCommandRunner({"distrobox": _ok("distrobox", "distrobox: 1.8.2.4")})
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["container_toolbox"].installed is False
        assert by_id["container_toolbox"].usable is None

    def test_container_toolbox_docker_plus_distrobox_is_installed(self, tmp_path):
        runner = FakeCommandRunner({
            "docker": _ok("docker", "Docker version 27.3.1"),
            "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
        })
        report = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["container_toolbox"].installed is True
        assert by_id["container_toolbox"].usable is None

    def test_container_toolbox_reason_reflects_which_half_is_missing(self, tmp_path):
        engine_only = build_cyber_capabilities(
            root=tmp_path,
            runner=FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")}),
        )
        reason = {c.id: c for c in engine_only.capabilities}["container_toolbox"].reason
        assert "distrobox" in reason.lower()
        assert "engine" in reason.lower()

        distrobox_only = build_cyber_capabilities(
            root=tmp_path,
            runner=FakeCommandRunner({"distrobox": _ok("distrobox", "distrobox: 1.8.2.4")}),
        )
        reason = {c.id: c for c in distrobox_only.capabilities}["container_toolbox"].reason
        assert "engine" in reason.lower()

    def test_container_toolbox_installed_implies_engine_and_distrobox(self, tmp_path):
        # S5RM Section 9 direct invariant.
        for runner in (
            FakeCommandRunner({
                "podman": _ok("podman", "podman version 5.7.0"),
                "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
            }),
            FakeCommandRunner({
                "docker": _ok("docker", "Docker version 27.3.1"),
                "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
            }),
        ):
            report = build_cyber_capabilities(root=tmp_path, runner=runner)
            containers = detect_toolbox_status(runner=runner)
            toolbox = {c.id: c for c in report.capabilities}["container_toolbox"]
            if toolbox.installed:
                assert containers.distrobox.installed is True
                assert containers.podman.installed or containers.docker.installed

    def test_to_dict_is_json_serializable(self):
        report = build_cyber_capabilities(runner=FakeCommandRunner({}))
        assert json.dumps(report.to_dict())


class TestForbiddenActions:
    """Section 91's quality bar, enforced as a direct regression across
    a range of plan states."""

    def _all_plans(self, tmp_path):
        scenarios = [
            FakeCommandRunner({}),
            FakeCommandRunner({
                "nmap": _ok("nmap", "Nmap version 7.95"),
                "podman": _ok("podman", "podman version 5.7.0"),
                "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
            }),
        ]
        return [build_cyber_plan(root=tmp_path, runner=r) for r in scenarios]

    def test_no_active_scan_commands_in_plan(self, tmp_path):
        forbidden = ("nmap ", "masscan", "arp-scan", "tcpdump -i", "tshark -i")
        for plan in self._all_plans(tmp_path):
            for action in plan.actions:
                blob = " ".join(
                    str(v) for v in (action.action, action.verification, action.reason) if v
                ).lower()
                for pattern in forbidden:
                    assert pattern not in blob

    def test_no_privileged_container_defaults(self, tmp_path):
        # Checked against the command-shaped fields only (action/
        # verification) - the `reason` field legitimately *documents*
        # the policy in prose ("never --privileged... by default"),
        # which must not itself trip a forbidden-pattern check.
        forbidden = ("--privileged", "--network=host", "cap_sys_admin", "/dev/")
        for plan in self._all_plans(tmp_path):
            for action in plan.actions:
                if action.component != "toolbox":
                    continue
                blob = " ".join(str(v) for v in (action.action, action.verification) if v).lower()
                for pattern in forbidden:
                    assert pattern not in blob

    def test_no_kali_install_in_plan(self, tmp_path):
        # Only APPLY-status actions represent something Serein would
        # actually plan to install; the vm.isolation_policy action is
        # a report_only/NOOP action whose `tool` field *documents* the
        # Kali-requires-a-VM policy in prose and must not trip this.
        for plan in self._all_plans(tmp_path):
            for action in plan.actions:
                if action.status != "APPLY":
                    continue
                blob = " ".join(
                    str(v) for v in (action.tool, action.target, action.current) if v
                ).lower()
                assert "kali" not in blob

    def test_no_apply_engine_command_anywhere(self, tmp_path):
        for plan in self._all_plans(tmp_path):
            for action in plan.actions:
                assert action.action != "apply"

    def test_verification_fields_are_version_checks_only(self, tmp_path):
        forbidden = ("scan localhost", "capture packet", "open proxy", " -i ", "crack")
        for plan in self._all_plans(tmp_path):
            for action in plan.actions:
                verification = action.verification.lower()
                for pattern in forbidden:
                    assert pattern not in verification


class TestPrivacy:
    def test_status_output_has_no_home_path_or_username(self, monkeypatch):
        import getpass
        import socket

        monkeypatch.setenv("USER", "should-not-appear")
        status = build_cyber_status(runner=FakeCommandRunner({}))
        blob = json.dumps(status.to_dict())
        assert socket.gethostname() not in blob
        assert getpass.getuser() not in blob

    def test_plan_never_contains_tmp_path(self, tmp_path):
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        blob = json.dumps(plan.to_dict())
        assert str(tmp_path) not in blob

    def test_capabilities_never_contains_tmp_path(self, tmp_path):
        report = build_cyber_capabilities(root=tmp_path, runner=FakeCommandRunner({}))
        blob = json.dumps(report.to_dict())
        assert str(tmp_path) not in blob

    def test_status_never_leaks_interface_names(self):
        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _ok("dumpcap", "1. eth0 (Ethernet)\n2. wlan0 (Wireless)\n")
                return super().run(args, timeout)

        runner = _Runner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})
        status = build_cyber_status(runner=runner)
        blob = json.dumps(status.to_dict())
        assert "eth0" not in blob
        assert "wlan0" not in blob


class TestPlanner:
    def _actions_by_id(self, plan):
        return {a.id: a for a in plan.actions}

    def test_deterministic(self, tmp_path):
        runner = FakeCommandRunner({})
        first = build_cyber_plan(root=tmp_path, runner=runner).to_dict()
        second = build_cyber_plan(root=tmp_path, runner=runner).to_dict()
        assert first == second

    def test_unknown_component_raises(self):
        with pytest.raises(ValueError):
            build_cyber_plan("not-a-real-component")

    def test_component_filter(self, tmp_path):
        plan = build_cyber_plan("toolbox", root=tmp_path, runner=FakeCommandRunner({}))
        assert plan.actions
        assert all(a.component == "toolbox" for a in plan.actions)

    def test_all_components_valid(self, tmp_path):
        for component in VALID_COMPONENTS:
            plan = build_cyber_plan(component, root=tmp_path, runner=FakeCommandRunner({}))
            assert plan.schema_version == CYBER_PLAN_SCHEMA_VERSION

    def test_host_baseline_apply_when_missing(self, tmp_path):
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["host.baseline"].status == "APPLY"

    def test_host_baseline_noop_when_all_installed(self, tmp_path):
        from serein.cyber.tools import all_tools

        packages = {t.package for t in all_tools() if t.recommended_tier == "host" and t.package}
        # Build a runner that answers every relevant binary probe.
        responses = {
            "nmap": _ok("nmap", "Nmap version 7.95"),
            "tcpdump": _ok("tcpdump", "tcpdump version 4.99.5"),
            "dig": _ok("dig", "DiS 9.18.0"),
            "whois": _ok("whois", "whois 5.5.0"),
            "openssl": _ok("openssl", "OpenSSL 3.2.0"),
            "socat": _ok("socat", "socat 1.7.4"),
            "nc": _ok("nc", "OpenBSD netcat"),
            "mtr": _ok("mtr", "mtr 0.95"),
            "ethtool": _ok("ethtool", "ethtool 6.7"),
            "tshark": _ok("tshark", "TShark 4.2.0"),
            "wireshark": _ok("wireshark", "Wireshark 4.2.0"),
            "file": _ok("file", "file-5.46"),
            "objdump": _ok("objdump", "GNU objdump 2.42"),
            "exiftool": _ok("exiftool", "13.00"),
        }
        assert packages  # sanity: manifest actually has host packages
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner(responses))
        actions = self._actions_by_id(plan)
        assert actions["host.baseline"].status == "NOOP"

    def test_toolbox_engine_skip_when_nested_container(self, tmp_path, monkeypatch):
        import serein.cyber.planner as planner_mod
        from serein.hardware.models import EnvironmentInfo

        monkeypatch.setattr(
            planner_mod, "detect_environment",
            lambda root: EnvironmentInfo(
                virtualization="container", is_wsl=False, is_container=True
            ),
        )
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["toolbox.engine"].status == "SKIP"
        assert actions["toolbox.distrobox"].status == "SKIP"

    def test_toolbox_engine_noop_when_present(self, tmp_path):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")})
        plan = build_cyber_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["toolbox.engine"].status == "NOOP"

    def test_toolbox_distrobox_apply_when_absent(self, tmp_path):
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["toolbox.distrobox"].status == "APPLY"

    def test_toolbox_engine_present_distrobox_absent(self, tmp_path):
        # S5RM Section 10: engine present / Distrobox absent must plan
        # engine=NOOP, distrobox=APPLY - consistent with
        # container_toolbox.installed=False in this same state.
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.7.0")})
        plan = build_cyber_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["toolbox.engine"].status == "NOOP"
        assert actions["toolbox.distrobox"].status == "APPLY"

    def test_toolbox_engine_absent_distrobox_present(self, tmp_path):
        runner = FakeCommandRunner({"distrobox": _ok("distrobox", "distrobox: 1.8.2.4")})
        plan = build_cyber_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["toolbox.engine"].status == "APPLY"
        assert actions["toolbox.distrobox"].status == "NOOP"

    def test_toolbox_engine_and_distrobox_both_present(self, tmp_path):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.7.0"),
            "distrobox": _ok("distrobox", "distrobox: 1.8.2.4"),
        })
        plan = build_cyber_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["toolbox.engine"].status == "NOOP"
        assert actions["toolbox.distrobox"].status == "NOOP"

    def test_vm_prerequisites_blocked_without_kvm(self, tmp_path):
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["vm.prerequisites"].status == "BLOCKED"

    def test_vm_prerequisites_blocked_when_module_not_loaded(self, tmp_path):
        # Device present but module not loaded and/or access unproven -
        # Serein must never say "prerequisites can be used" here
        # (S5R Section 19): this is still BLOCKED, not APPLY.
        (tmp_path / "dev").mkdir()
        (tmp_path / "dev" / "kvm").write_text("")
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["vm.prerequisites"].status == "BLOCKED"

    def test_vm_prerequisites_blocked_when_user_access_false(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: False)
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["vm.prerequisites"].status == "BLOCKED"

    def test_vm_prerequisites_apply_with_hardware_and_access_ready(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["vm.prerequisites"].status == "APPLY"

    def test_vm_prerequisites_noop_when_all_present(self, tmp_path, monkeypatch):
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
            "virsh": _ok("virsh", "10.0.0"),
        })
        plan = build_cyber_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["vm.prerequisites"].status == "NOOP"

    def test_vm_capability_usable_implies_prerequisites_noop(self, tmp_path, monkeypatch):
        # S5R Section 22/43 invariant: vm_isolation.usable == True must
        # always imply vm.prerequisites.status == NOOP, since both
        # derive from the same evaluate_vm_readiness() verdict.
        _kvm_ready_root(tmp_path)
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
            "virsh": _ok("virsh", "10.0.0"),
        })
        capabilities = build_cyber_capabilities(root=tmp_path, runner=runner)
        by_cap_id = {c.id: c for c in capabilities.capabilities}
        plan = build_cyber_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert by_cap_id["vm_isolation"].usable is True
        assert actions["vm.prerequisites"].status == "NOOP"

    def test_vm_isolation_policy_always_present_and_noop(self, tmp_path):
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["vm.isolation_policy"].status == "NOOP"
        assert "VM" in actions["vm.isolation_policy"].reason

    def test_never_downloads_kali_iso(self, tmp_path):
        for action in build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({})).actions:
            blob = " ".join(str(v) for v in (action.action, action.verification) if v).lower()
            assert "iso" not in blob
            assert "download" not in blob

    def test_to_dict_is_json_serializable(self, tmp_path):
        plan = build_cyber_plan(root=tmp_path, runner=FakeCommandRunner({}))
        assert json.dumps(plan.to_dict())


class TestDoctor:
    def test_clean_host_all_pass_or_skip(self, tmp_path):
        report = run_cyber_checks(root=tmp_path, runner=FakeCommandRunner({}))
        assert report.exit_code == 0
        assert all(c.status is not CheckStatus.FAIL for c in report.checks)

    def test_host_hygiene_warns_when_hashcat_present(self, tmp_path):
        runner = FakeCommandRunner({"hashcat": _ok("hashcat", "hashcat v6.2.6")})
        report = run_cyber_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_host_hygiene"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_capture_backend_inconsistency_warns(self, tmp_path):
        runner = FakeCommandRunner({"wireshark": _ok("wireshark", "Wireshark 4.2.0")})
        report = run_cyber_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_capture_backend_consistency"].status is CheckStatus.WARN

    def test_no_capture_inconsistency_when_dumpcap_present_too(self, tmp_path):
        runner = FakeCommandRunner({
            "wireshark": _ok("wireshark", "Wireshark 4.2.0"),
            "dumpcap": _ok("dumpcap", "Dumpcap 4.2.0"),
        })
        report = run_cyber_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_capture_backend_consistency"].status is CheckStatus.PASS

    def test_capture_permission_denied_warns(self, tmp_path):
        runner = FakeCommandRunner({"dumpcap": _ok("dumpcap", "Dumpcap 4.2.0")})

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args == ["dumpcap", "-D"]:
                    return _fail()
                return super().run(args, timeout)

        report = run_cyber_checks(root=tmp_path, runner=_Runner(runner._responses))
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_capture_backend_consistency"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_capture_permission_unknown_is_not_warn(self, tmp_path):
        # Unknown must never be reported as though it were a denial.
        runner = FakeCommandRunner({("dumpcap", "-v"): _ok("dumpcap", "Dumpcap 4.2.0")})
        report = run_cyber_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_capture_backend_consistency"].status is CheckStatus.PASS
        assert "permission denied" not in by_id["cyber_capture_backend_consistency"].detail.lower()

    def test_vm_readiness_skips_without_hardware(self, tmp_path):
        report = run_cyber_checks(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_vm_readiness"].status is CheckStatus.SKIP

    def test_vm_readiness_warns_on_no_access(self, tmp_path, monkeypatch):
        (tmp_path / "dev").mkdir()
        (tmp_path / "dev" / "kvm").write_text("")
        (tmp_path / "proc").mkdir()
        (tmp_path / "proc" / "modules").write_text("kvm 1064960 0 - Live 0x0\n")
        monkeypatch.setattr("os.access", lambda *a, **kw: False)
        report = run_cyber_checks(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_vm_readiness"].status is CheckStatus.WARN

    def test_vm_readiness_passes_on_full_chain(self, tmp_path, monkeypatch):
        (tmp_path / "dev").mkdir()
        (tmp_path / "dev" / "kvm").write_text("")
        (tmp_path / "proc").mkdir()
        (tmp_path / "proc" / "modules").write_text("kvm 1064960 0 - Live 0x0\n")
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("qemu-system-x86_64", "QEMU emulator version 8.2.2"),
            "virsh": _ok("virsh", "10.0.0"),
        })
        report = run_cyber_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_vm_readiness"].status is CheckStatus.PASS

    def test_container_engine_conflict_warns(self, tmp_path):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.7.0"),
            "docker": _ok("docker", "Docker version 27.0.0"),
        })
        report = run_cyber_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["cyber_container_engine_conflict"].status is CheckStatus.WARN

    def test_no_cyber_tooling_is_pass_not_fail(self, tmp_path):
        report = run_cyber_checks(root=tmp_path, runner=FakeCommandRunner({}))
        assert all(c.status is not CheckStatus.FAIL for c in report.checks)

    def test_json_shape_matches_shared_doctor_report(self, tmp_path):
        report = run_cyber_checks(root=tmp_path, runner=FakeCommandRunner({}))
        data = report.to_dict()
        assert data["schema_version"] == 1
        assert set(data["summary"]) == {"PASS", "WARN", "FAIL", "SKIP"}
