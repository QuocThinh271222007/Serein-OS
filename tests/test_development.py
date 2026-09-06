"""Development subsystem tests. Every detection call uses a
FakeCommandRunner and an explicitly injected ``home`` — never the real
host's PATH or home directory — so tests are independent of whatever
happens to be installed on the machine running them.

S3R corrective: the original suite let several call sites default
``home=None``, which falls back to the *real* ``$HOME``. On a GitHub
Actions runner that already has Node/NVM-related state pre-installed
(a common `setup-node`-style side effect), a test that intended "clean
workstation" silently observed the runner's real home instead and
produced a different result than on a genuinely clean machine (see
``test_home_isolation_is_not_contaminated_by_a_populated_default_home``
below and docs/development/node-strategy.md's "Node manager conflict
state machine" section). Every test in this file now uses the
``clean_home`` fixture (a fresh ``tmp_path``) instead of relying on a
default, even where the scenario doesn't currently exercise a marker -
that keeps the whole suite hermetic by construction, not by accident.
"""

from __future__ import annotations

import json

import pytest

from serein.development.capabilities import build_development_capabilities
from serein.development.containers import (
    container_capability_available,
    detect_container_status,
)
from serein.development.cpp import (
    cpp_installed_map,
    cpp_toolchain_fully_installed,
    detect_cpp_status,
)
from serein.development.doctor import run_development_checks
from serein.development.dpkg import apt_package_installed
from serein.development.editor import detect_editor_status
from serein.development.git import detect_git_status
from serein.development.go import detect_go_status
from serein.development.models import (
    DEV_CAPABILITIES_SCHEMA_VERSION,
    DEV_PLAN_SCHEMA_VERSION,
)
from serein.development.node import detect_node_status
from serein.development.packages import (
    ALL_GROUPS,
    CPP_TOOLS,
    all_tools,
    default_apt_packages,
)
from serein.development.planner import VALID_COMPONENTS, build_development_plan
from serein.development.python import detect_python_status
from serein.development.runner import CommandResult, SubprocessCommandRunner
from serein.development.rust import detect_rust_status
from serein.doctor.models import CheckStatus
from serein.hardware.models import EnvironmentInfo


@pytest.fixture
def clean_home(tmp_path):
    """A fresh, guaranteed-empty home directory - never the real
    ``$HOME`` of the developer or CI runner. Use this (not a bare
    ``tmp_path`` and never an implicit ``home=None``) for every test
    whose semantics depend on filesystem-marker detection (nvm/pyenv/
    conda/micromamba/Zed) or that simply wants a deterministic "clean
    workstation" baseline."""
    return tmp_path


class FakeCommandRunner:
    """Maps a binary name to a canned CommandResult (or None = "not
    found"). Records every call for tests that need to assert on
    invocation without ever actually running anything."""

    def __init__(self, responses: dict[str, CommandResult | None]):
        self._responses = responses
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):
        self.calls.append(list(args))
        binary = args[0]
        if binary not in self._responses:
            return None
        return self._responses[binary]


def _ok(binary: str, version_line: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=version_line, stderr="")


class _DpkgAwareRunner:
    """A FakeCommandRunner variant that answers dpkg-query per-package
    (the plain FakeCommandRunner only keys on the binary name, which
    can't distinguish "dpkg-query build-essential" from "dpkg-query
    gdb"). Everything else defers to an inner FakeCommandRunner."""

    def __init__(self, responses: dict[str, CommandResult | None], dpkg_installed: set[str]):
        self._inner = FakeCommandRunner(responses)
        self._dpkg_installed = dpkg_installed
        self.calls: list[list[str]] = self._inner.calls

    def run(self, args, timeout: float = 3.0):
        if args[0] == "dpkg-query":
            package = args[-1]
            self.calls.append(list(args))
            if package in self._dpkg_installed:
                return _ok("dpkg-query", "install ok installed")
            return CommandResult(returncode=1, stdout="", stderr="no packages found")
        return self._inner.run(args, timeout=timeout)


def _bare_environment() -> EnvironmentInfo:
    return EnvironmentInfo(virtualization="none", is_wsl=False, is_container=False)


def _container_environment() -> EnvironmentInfo:
    return EnvironmentInfo(virtualization="container", is_wsl=False, is_container=True)


class TestRunner:
    def test_subprocess_runner_degrades_on_missing_binary(self):
        runner = SubprocessCommandRunner()
        result = runner.run(["serein-definitely-not-a-real-binary-xyz", "--version"])
        assert result is None

    def test_subprocess_runner_never_raises_on_timeout(self):
        runner = SubprocessCommandRunner()
        # A command that should exist but with a timeout so small it can't
        # possibly respond in time - must degrade to None, not raise.
        result = runner.run(["python", "-c", "import time; time.sleep(5)"], timeout=0.01)
        assert result is None


class TestGit:
    def test_all_installed(self):
        runner = FakeCommandRunner({
            "git": _ok("git", "git version 2.43.0"),
            "git-lfs": _ok("git-lfs", "git-lfs/3.4.0"),
            "gh": _ok("gh", "gh version 2.40.0"),
        })
        status = detect_git_status(runner)
        assert status.git.installed and status.git.version == "2.43.0"
        assert status.git_lfs.installed
        assert status.gh.installed

    def test_none_installed(self):
        runner = FakeCommandRunner({})
        status = detect_git_status(runner)
        assert not status.git.installed
        assert not status.git_lfs.installed
        assert not status.gh.installed


class TestPython:
    def test_system_python_and_uv(self, clean_home):
        runner = FakeCommandRunner({
            "python3": _ok("python3", "Python 3.12.3"),
            "uv": _ok("uv", "uv 0.4.18"),
        })
        status = detect_python_status(runner, home=clean_home)
        assert status.system_python.installed
        assert status.uv.installed

    def test_pyenv_detected_via_marker(self, clean_home):
        (clean_home / ".pyenv").mkdir()
        status = detect_python_status(FakeCommandRunner({}), home=clean_home)
        assert status.pyenv_present is True
        assert status.conda_present is False

    def test_conda_detected_via_marker_directory(self, clean_home):
        (clean_home / "miniconda3").mkdir()
        status = detect_python_status(FakeCommandRunner({}), home=clean_home)
        assert status.conda_present is True

    def test_conda_detected_via_binary(self, clean_home):
        runner = FakeCommandRunner({"conda": _ok("conda", "conda 24.1.0")})
        status = detect_python_status(runner, home=clean_home)
        assert status.conda_present is True

    def test_no_managers_present(self, clean_home):
        status = detect_python_status(FakeCommandRunner({}), home=clean_home)
        assert status.pyenv_present is False
        assert status.conda_present is False
        assert status.micromamba.installed is False

    def test_system_python_never_targeted_for_mutation(self, clean_home):
        # Regression: no plan action anywhere may reference pip against
        # the system interpreter. See TestForbiddenActions for the
        # full-plan sweep; this asserts the source data has no such path.
        runner = FakeCommandRunner({"python3": _ok("python3", "Python 3.12.3")})
        plan = build_development_plan("python", runner=runner, home=clean_home)
        for action in plan.actions:
            assert "pip" not in action.action
            assert "sudo" not in (action.verification or "")


class TestNode:
    def test_nvm_is_marker_based_not_a_binary(self, clean_home):
        (clean_home / ".nvm").mkdir()
        (clean_home / ".nvm" / "nvm.sh").write_text("# nvm shell function stub\n")
        status = detect_node_status(FakeCommandRunner({}), home=clean_home)
        assert status.nvm_present is True
        assert status.manager_count == 1
        assert status.managers == ("nvm",)

    def test_fnm_and_mise_are_real_binaries(self, clean_home):
        runner = FakeCommandRunner({
            "fnm": _ok("fnm", "fnm 1.35.0"),
            "mise": _ok("mise", "2024.1.0"),
        })
        status = detect_node_status(runner, home=clean_home)
        assert status.fnm.installed and status.mise.installed
        assert status.manager_count == 2
        assert status.managers == ("fnm", "mise")

    def test_no_manager(self, clean_home):
        status = detect_node_status(FakeCommandRunner({}), home=clean_home)
        assert status.manager_count == 0
        assert status.managers == ()

    def test_node_without_any_manager(self, clean_home):
        runner = FakeCommandRunner({"node": _ok("node", "v20.11.0")})
        status = detect_node_status(runner, home=clean_home)
        assert status.node.installed
        assert status.manager_count == 0

    def test_home_isolation_is_not_contaminated_by_a_populated_default_home(
        self, tmp_path, monkeypatch
    ):
        """Direct regression for the S3R CI failure: point the real
        default-home resolution at a directory that DOES have ~/.nvm
        (simulating a GitHub runner with pre-existing Node tooling),
        then prove that a caller passing an explicit, isolated
        ``clean_home`` still sees a clean result regardless."""
        import serein.development.node as node_mod

        populated_default_home = tmp_path / "populated-default-home"
        (populated_default_home / ".nvm").mkdir(parents=True)
        (populated_default_home / ".nvm" / "nvm.sh").write_text("")
        # node.py imports `default_home` by name (`from ... import
        # default_home`), so the patch target is node.py's own binding,
        # not _util.default_home itself.
        monkeypatch.setattr(node_mod, "default_home", lambda: populated_default_home)

        isolated_home = tmp_path / "isolated-clean-home"
        isolated_home.mkdir()

        contaminated = detect_node_status(FakeCommandRunner({}), home=None)
        isolated = detect_node_status(FakeCommandRunner({}), home=isolated_home)

        assert contaminated.nvm_present is True
        assert isolated.nvm_present is False


class TestRust:
    def test_rustup_present(self):
        runner = FakeCommandRunner({"rustup": _ok("rustup", "rustup 1.27.0")})
        status = detect_rust_status(runner)
        assert status.rustup.installed

    def test_distro_rust_only(self):
        runner = FakeCommandRunner({
            "rustc": _ok("rustc", "rustc 1.75.0"),
            "cargo": _ok("cargo", "cargo 1.75.0"),
        })
        status = detect_rust_status(runner)
        assert not status.rustup.installed
        assert status.rustc.installed and status.cargo.installed

    def test_missing_rust(self):
        status = detect_rust_status(FakeCommandRunner({}))
        assert not status.rustup.installed
        assert not status.rustc.installed


class TestGo:
    def test_go_installed(self):
        runner = FakeCommandRunner({"go": _ok("go", "go version go1.26.0 linux/amd64")})
        status = detect_go_status(runner)
        assert status.go.installed
        assert status.go.version == "1.26.0"

    def test_go_absent(self):
        status = detect_go_status(FakeCommandRunner({}))
        assert not status.go.installed


class TestCpp:
    _ALL_BINARIES = ("gcc", "g++", "clang", "cmake", "ninja", "gdb", "lldb", "pkg-config", "strace")

    def test_all_present_including_build_essential(self):
        runner = _DpkgAwareRunner(
            {t: _ok(t, f"{t} 1.0") for t in self._ALL_BINARIES},
            dpkg_installed={"build-essential"},
        )
        status = detect_cpp_status(runner)
        assert all([
            status.gcc.installed, status.gpp.installed, status.clang.installed,
            status.cmake.installed, status.ninja.installed, status.gdb.installed,
            status.lldb.installed, status.pkg_config.installed, status.strace.installed,
        ])
        assert status.build_essential_installed is True
        assert cpp_toolchain_fully_installed(status) is True

    def test_none_present(self):
        status = detect_cpp_status(FakeCommandRunner({}))
        assert not status.gcc.installed
        assert not status.clang.installed
        assert status.build_essential_installed is False
        assert cpp_toolchain_fully_installed(status) is False

    def test_gcc_present_does_not_imply_build_essential_installed(self):
        """The exact S3R defect: gcc being on PATH must never be read
        as evidence that the build-essential metapackage is
        installed - they are independent facts."""
        runner = _DpkgAwareRunner(
            {"gcc": _ok("gcc", "gcc 13.0")},
            dpkg_installed=set(),
        )
        status = detect_cpp_status(runner)
        assert status.gcc.installed is True
        assert status.build_essential_installed is False
        assert cpp_toolchain_fully_installed(status) is False

    def test_build_essential_installed_but_clang_missing(self):
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in self._ALL_BINARIES if t != "clang"},
            dpkg_installed={"build-essential"},
        )
        status = detect_cpp_status(runner)
        assert status.build_essential_installed is True
        assert status.clang.installed is False
        assert cpp_toolchain_fully_installed(status) is False

    def test_everything_except_lldb(self):
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in self._ALL_BINARIES if t != "lldb"},
            dpkg_installed={"build-essential"},
        )
        status = detect_cpp_status(runner)
        assert status.lldb.installed is False
        assert cpp_toolchain_fully_installed(status) is False

    def test_installed_map_matches_cpp_tools_package_ids(self):
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in self._ALL_BINARIES},
            dpkg_installed={"build-essential"},
        )
        status = detect_cpp_status(runner)
        installed_map = cpp_installed_map(status)
        cpp_tool_packages = {t.package for t in CPP_TOOLS}
        assert set(installed_map) == cpp_tool_packages
        assert all(installed_map.values())


class TestDpkg:
    def test_apt_package_installed_true(self):
        runner = FakeCommandRunner({"dpkg-query": _ok("dpkg-query", "install ok installed")})
        assert apt_package_installed("build-essential", runner) is True

    def test_apt_package_installed_false_on_nonzero_exit(self):
        runner = FakeCommandRunner(
            {"dpkg-query": CommandResult(returncode=1, stdout="", stderr="no packages found")}
        )
        assert apt_package_installed("build-essential", runner) is False

    def test_apt_package_installed_false_when_dpkg_unavailable(self):
        # e.g. this repository's own Windows dev host, or any non-Debian
        # machine: dpkg-query simply isn't found, never raises.
        assert apt_package_installed("build-essential", FakeCommandRunner({})) is False

    def test_never_shells_out_with_shell_true(self):
        # SubprocessCommandRunner is the only real runner and always
        # passes shell=False; this just documents the read-only,
        # argv-list invocation shape used.
        runner = FakeCommandRunner({"dpkg-query": _ok("dpkg-query", "install ok installed")})
        apt_package_installed("build-essential", runner)
        assert runner.calls[-1] == ["dpkg-query", "-W", "-f=${Status}", "build-essential"]


class TestEditor:
    def test_zed_via_version_probe(self, clean_home):
        runner = FakeCommandRunner({"zed": _ok("zed", "Zed 0.145.0")})
        status = detect_editor_status(runner, home=clean_home)
        assert status.zed.installed

    def test_zed_via_marker_fallback(self, clean_home):
        marker = clean_home / ".local" / "bin" / "zed"
        marker.parent.mkdir(parents=True)
        marker.write_text("")
        status = detect_editor_status(FakeCommandRunner({}), home=clean_home)
        assert status.zed.installed is True

    def test_zed_absent(self, clean_home):
        status = detect_editor_status(FakeCommandRunner({}), home=clean_home)
        assert status.zed.installed is False


class TestContainers:
    def test_podman_only(self):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.0.0")})
        status = detect_container_status(runner)
        assert status.podman.installed and not status.docker.installed

    def test_docker_only(self):
        runner = FakeCommandRunner({"docker": _ok("docker", "Docker version 25.0.0")})
        status = detect_container_status(runner)
        assert status.docker.installed and not status.podman.installed

    def test_both(self):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "docker": _ok("docker", "Docker version 25.0.0"),
        })
        status = detect_container_status(runner)
        assert status.podman.installed and status.docker.installed

    def test_neither(self):
        status = detect_container_status(FakeCommandRunner({}))
        assert not status.podman.installed and not status.docker.installed

    def test_capability_available_bare_metal(self):
        assert container_capability_available(_bare_environment()) is True

    def test_capability_unavailable_nested_container(self):
        assert container_capability_available(_container_environment()) is False


class TestPackages:
    def test_all_tools_no_duplicate_ids(self):
        tools = all_tools()
        ids = [t.id for t in tools]
        assert len(ids) == len(set(ids))

    def test_default_apt_packages_sorted_deduplicated(self):
        packages = default_apt_packages()
        assert packages == sorted(set(packages))
        assert len(packages) > 0

    def test_p7zip_full_not_present_7zip_is(self):
        packages = default_apt_packages()
        assert "p7zip-full" not in packages
        assert "7zip" in packages

    def test_yq_excluded_due_to_identity_ambiguity(self):
        assert "yq" not in default_apt_packages()

    def test_docker_not_in_default_packages(self):
        assert "docker" not in default_apt_packages()
        assert "docker.io" not in default_apt_packages()

    def test_no_kitchen_sink_or_ai_packages(self):
        packages = default_apt_packages()
        forbidden = ("cuda", "nvidia-driver", "kali", "nmap", "tor", "burpsuite")
        for name in forbidden:
            assert name not in packages

    def test_every_tool_has_a_recognized_source_type(self):
        allowed = {
            "ubuntu-repository", "official-upstream-repository",
            "official-upstream-binary", "language-bootstrap-tool",
            "user-installed", "optional",
        }
        for tool in all_tools():
            assert tool.source_type in allowed

    def test_all_groups_are_tuples_of_tool_definitions(self):
        for _name, tools in ALL_GROUPS:
            assert isinstance(tools, tuple)
            assert len(tools) > 0


class TestCapabilities:
    def test_schema_version(self, clean_home):
        report = build_development_capabilities(runner=FakeCommandRunner({}), home=clean_home)
        assert report.schema_version == DEV_CAPABILITIES_SCHEMA_VERSION

    def test_all_ids_present_exactly_once(self, clean_home):
        report = build_development_capabilities(runner=FakeCommandRunner({}), home=clean_home)
        ids = [c.id for c in report.capabilities]
        assert len(ids) == len(set(ids)) == 11

    def test_language_toolchains_available_everywhere(self, clean_home):
        report = build_development_capabilities(runner=FakeCommandRunner({}), home=clean_home)
        by_id = {c.id: c for c in report.capabilities}
        for cap_id in ("python_uv", "node_runtime", "rustup", "go_toolchain", "cpp_toolchain"):
            assert by_id[cap_id].available is True

    def test_zed_capability_is_medium_confidence(self, clean_home):
        report = build_development_capabilities(runner=FakeCommandRunner({}), home=clean_home)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["zed_editor"].confidence == "medium"

    def test_to_dict_is_json_serializable(self, clean_home):
        report = build_development_capabilities(runner=FakeCommandRunner({}), home=clean_home)
        assert json.dumps(report.to_dict())

    def test_cpp_toolchain_capability_reflects_build_essential_state(self, clean_home):
        # Everything but the build-essential *package* present: the
        # capability must not claim the toolchain is installed.
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in TestCpp._ALL_BINARIES},
            dpkg_installed=set(),
        )
        report = build_development_capabilities(runner=runner, home=clean_home)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["cpp_toolchain"].installed is False

    def test_cpp_toolchain_capability_true_only_when_fully_installed(self, clean_home):
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in TestCpp._ALL_BINARIES},
            dpkg_installed={"build-essential"},
        )
        report = build_development_capabilities(runner=runner, home=clean_home)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["cpp_toolchain"].installed is True


class TestForbiddenActions:
    """Section 98's quality bar, enforced as a direct regression: scan
    every plan action produced across a wide range of states for any
    forbidden action pattern."""

    def _all_plans(self, clean_home):
        scenarios = [
            FakeCommandRunner({}),
            FakeCommandRunner({
                "git": _ok("git", "git version 2.43.0"),
                "python3": _ok("python3", "Python 3.12.3"),
                "node": _ok("node", "v20.11.0"),
                "rustc": _ok("rustc", "rustc 1.75.0"),
                "go": _ok("go", "go version go1.26.0 linux/amd64"),
                "podman": _ok("podman", "podman version 5.0.0"),
            }),
        ]
        return [build_development_plan(runner=r, home=clean_home) for r in scenarios]

    def test_no_sudo_pip(self, clean_home):
        for plan in self._all_plans(clean_home):
            for action in plan.actions:
                blob = " ".join(
                    str(v) for v in (action.action, action.verification, action.reason) if v
                )
                assert "sudo pip" not in blob
                assert "sudo -H pip" not in blob

    def test_no_sudo_npm(self, clean_home):
        for plan in self._all_plans(clean_home):
            for action in plan.actions:
                blob = " ".join(
                    str(v) for v in (action.action, action.verification, action.reason) if v
                )
                assert "sudo npm" not in blob

    def test_no_apply_engine_command_anywhere(self, clean_home):
        # There is no "apply" action type in S3 at all.
        for plan in self._all_plans(clean_home):
            for action in plan.actions:
                assert action.action != "apply"


class TestPrivacy:
    def test_status_output_has_no_home_path_or_username(self, clean_home, monkeypatch):
        import getpass
        import socket

        from serein.development.status import build_development_status

        monkeypatch.setenv("USER", "should-not-appear")
        status = build_development_status(runner=FakeCommandRunner({}), home=clean_home)
        blob = json.dumps(
            {
                "git": vars(status.git.git),
                "python": {"uv": vars(status.python.uv)},
            }
        )
        assert str(clean_home) not in blob
        assert socket.gethostname() not in blob
        assert getpass.getuser() not in blob

    def test_plan_never_contains_tmp_path(self, clean_home):
        plan = build_development_plan(runner=FakeCommandRunner({}), home=clean_home)
        blob = json.dumps(plan.to_dict())
        assert str(clean_home) not in blob


class TestPlanner:
    def test_deterministic(self, clean_home):
        runner = FakeCommandRunner({"git": _ok("git", "git version 2.43.0")})
        first = build_development_plan(runner=runner, home=clean_home).to_dict()
        second = build_development_plan(runner=runner, home=clean_home).to_dict()
        assert first == second

    def test_unknown_component_raises(self):
        with pytest.raises(ValueError):
            build_development_plan("not-a-real-component")

    def test_component_filter_returns_only_matching_actions(self, clean_home):
        plan = build_development_plan("rust", runner=FakeCommandRunner({}), home=clean_home)
        assert plan.actions
        assert all(a.component == "rust" for a in plan.actions)

    def test_all_components_are_valid_filters(self, clean_home):
        for component in VALID_COMPONENTS:
            plan = build_development_plan(component, runner=FakeCommandRunner({}), home=clean_home)
            assert plan.schema_version == DEV_PLAN_SCHEMA_VERSION

    def _actions_by_id(self, plan):
        return {a.id: a for a in plan.actions}

    # --- Node manager state machine (S3R corrective) --------------------
    #
    # State model (docs/development/node-strategy.md):
    #   0 managers                    -> APPLY fnm
    #   1 manager, it is fnm          -> NOOP
    #   1 manager, it is NOT fnm      -> BLOCKED
    #   >1 managers (fnm included or not) -> BLOCKED

    def test_node_no_manager_applies_fnm(self, clean_home):
        plan = build_development_plan("node", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "APPLY"
        assert actions["node.manager"].tool == "fnm"

    def test_node_single_fnm_is_noop(self, clean_home):
        runner = FakeCommandRunner({"fnm": _ok("fnm", "fnm 1.35.0")})
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "NOOP"

    def test_node_single_mise_is_blocked(self, clean_home):
        runner = FakeCommandRunner({"mise": _ok("mise", "2024.1.0")})
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "BLOCKED"
        assert actions["node.manager"].target == "fnm"

    def test_node_single_nvm_is_blocked(self, clean_home):
        (clean_home / ".nvm").mkdir()
        (clean_home / ".nvm" / "nvm.sh").write_text("")
        plan = build_development_plan("node", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "BLOCKED"

    @pytest.mark.parametrize(
        "present",
        [
            ("fnm", "mise"),
            ("fnm", "nvm"),
            ("mise", "nvm"),
            ("fnm", "mise", "nvm"),
        ],
    )
    def test_node_multi_manager_always_blocked(self, clean_home, present):
        responses = {}
        if "fnm" in present:
            responses["fnm"] = _ok("fnm", "fnm 1.35.0")
        if "mise" in present:
            responses["mise"] = _ok("mise", "2024.1.0")
        if "nvm" in present:
            (clean_home / ".nvm").mkdir()
            (clean_home / ".nvm" / "nvm.sh").write_text("")
        plan = build_development_plan(
            "node", runner=FakeCommandRunner(responses), home=clean_home
        )
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "BLOCKED", present

    def test_node_manager_blocked_never_layers_second_manager(self, clean_home):
        # Explicit Section 60 regression: even with mise present, the
        # planner must not silently propose installing fnm on top.
        runner = FakeCommandRunner({"mise": _ok("mise", "2024.1.0")})
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "BLOCKED"
        assert actions["node.manager"].target == "fnm"

    # --- pnpm / Node-manager-conflict dependency -------------------------

    def test_pnpm_apply_when_absent_and_no_manager_conflict(self, clean_home):
        plan = build_development_plan("node", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.pnpm"].status == "APPLY"

    def test_pnpm_noop_when_present(self, clean_home):
        runner = FakeCommandRunner({"pnpm": _ok("pnpm", "8.15.0")})
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.pnpm"].status == "NOOP"

    def test_pnpm_blocked_when_node_manager_conflict_single_other(self, clean_home):
        runner = FakeCommandRunner({"mise": _ok("mise", "2024.1.0")})
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "BLOCKED"
        assert actions["node.pnpm"].status == "BLOCKED"

    def test_pnpm_blocked_when_node_manager_conflict_multi(self, clean_home):
        runner = FakeCommandRunner({
            "fnm": _ok("fnm", "fnm 1.35.0"),
            "mise": _ok("mise", "2024.1.0"),
        })
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.manager"].status == "BLOCKED"
        assert actions["node.pnpm"].status == "BLOCKED"

    def test_pnpm_present_is_noop_even_during_manager_conflict(self, clean_home):
        # pnpm already installed - never re-litigate NOOP into BLOCKED.
        runner = FakeCommandRunner({
            "mise": _ok("mise", "2024.1.0"),
            "pnpm": _ok("pnpm", "8.15.0"),
        })
        plan = build_development_plan("node", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["node.pnpm"].status == "NOOP"

    # --- Rust / Go -------------------------------------------------------

    def test_rustup_noop_when_present(self, clean_home):
        runner = FakeCommandRunner({"rustup": _ok("rustup", "rustup 1.27.0")})
        plan = build_development_plan("rust", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["rust.rustup"].status == "NOOP"

    def test_rustup_apply_when_distro_rust_only(self, clean_home):
        runner = FakeCommandRunner({"rustc": _ok("rustc", "rustc 1.75.0")})
        plan = build_development_plan("rust", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["rust.rustup"].status == "APPLY"
        assert "distro Rust" in actions["rust.rustup"].current

    def test_rustup_apply_when_nothing_present(self, clean_home):
        plan = build_development_plan("rust", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["rust.rustup"].status == "APPLY"

    def test_go_noop_when_already_installed(self, clean_home):
        runner = FakeCommandRunner({"go": _ok("go", "go version go1.26.0 linux/amd64")})
        plan = build_development_plan("go", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["go.toolchain"].status == "NOOP"

    def test_go_apply_when_absent(self, clean_home):
        plan = build_development_plan("go", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["go.toolchain"].status == "APPLY"

    # --- C/C++ package-state (S3R corrective) ----------------------------

    def test_cpp_apply_when_missing_subset(self, clean_home):
        runner = _DpkgAwareRunner({"gcc": _ok("gcc", "gcc 13.0")}, dpkg_installed=set())
        plan = build_development_plan("cpp", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["cpp.toolchain"].status == "APPLY"
        assert "gcc" not in actions["cpp.toolchain"].reason.split("Missing package(s): ")[1]

    def test_cpp_apply_when_gcc_present_but_build_essential_package_absent(self, clean_home):
        """The exact S3R defect regression: gcc alone must not cause
        Serein to believe build-essential is satisfied."""
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in TestCpp._ALL_BINARIES},
            dpkg_installed=set(),
        )
        plan = build_development_plan("cpp", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["cpp.toolchain"].status == "APPLY"
        assert "build-essential" in actions["cpp.toolchain"].reason

    def test_cpp_noop_when_all_present(self, clean_home):
        runner = _DpkgAwareRunner(
            {t: _ok(t, "1.0") for t in TestCpp._ALL_BINARIES},
            dpkg_installed={"build-essential"},
        )
        plan = build_development_plan("cpp", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["cpp.toolchain"].status == "NOOP"

    def test_cpp_capability_plan_consistency_invariant(self, clean_home):
        """S2RM-style invariant, applied to C/C++: capabilities and the
        planner must never disagree about whether the toolchain is
        fully present."""
        scenarios = [
            _DpkgAwareRunner({}, dpkg_installed=set()),
            _DpkgAwareRunner(
                {t: _ok(t, "1.0") for t in TestCpp._ALL_BINARIES}, dpkg_installed=set()
            ),
            _DpkgAwareRunner(
                {t: _ok(t, "1.0") for t in TestCpp._ALL_BINARIES},
                dpkg_installed={"build-essential"},
            ),
        ]
        for runner in scenarios:
            report = build_development_capabilities(runner=runner, home=clean_home)
            plan = build_development_plan("cpp", runner=runner, home=clean_home)
            cpp_capability = next(c for c in report.capabilities if c.id == "cpp_toolchain")
            cpp_action = next(a for a in plan.actions if a.id == "cpp.toolchain")
            if cpp_capability.installed:
                assert cpp_action.status == "NOOP", runner
            else:
                assert cpp_action.status == "APPLY", runner

    # --- Containers / editor / python conflicts --------------------------

    def test_containers_apply_when_absent(self, clean_home):
        plan = build_development_plan(
            "containers", runner=FakeCommandRunner({}), home=clean_home
        )
        actions = self._actions_by_id(plan)
        assert actions["containers.engine"].status == "APPLY"
        assert actions["containers.engine"].tool == "podman"

    def test_containers_noop_when_either_present(self, clean_home):
        runner = FakeCommandRunner({"docker": _ok("docker", "Docker version 25.0.0")})
        plan = build_development_plan("containers", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["containers.engine"].status == "NOOP"

    def test_containers_skip_when_nested_container(self, clean_home, monkeypatch):
        import serein.development.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_environment", lambda root: _container_environment()
        )
        plan = build_development_plan(
            "containers", runner=FakeCommandRunner({}), home=clean_home
        )
        actions = self._actions_by_id(plan)
        assert actions["containers.engine"].status == "SKIP"
        assert actions["containers.distrobox"].status == "SKIP"

    def test_editor_apply_when_absent(self, clean_home):
        plan = build_development_plan("editor", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["editor.zed"].status == "APPLY"

    def test_editor_noop_when_present(self, clean_home):
        runner = FakeCommandRunner({"zed": _ok("zed", "Zed 0.145.0")})
        plan = build_development_plan("editor", runner=runner, home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["editor.zed"].status == "NOOP"

    def test_python_conflict_reports_without_removing(self, clean_home):
        (clean_home / ".pyenv").mkdir()
        plan = build_development_plan("python", runner=FakeCommandRunner({}), home=clean_home)
        actions = self._actions_by_id(plan)
        assert actions["python.existing_managers"].status == "NOOP"
        assert "pyenv" in actions["python.existing_managers"].current

    def test_to_dict_is_json_serializable(self, clean_home):
        plan = build_development_plan(runner=FakeCommandRunner({}), home=clean_home)
        assert json.dumps(plan.to_dict())


class TestDoctor:
    def test_clean_host_all_pass_or_skip(self, clean_home):
        report = run_development_checks(runner=FakeCommandRunner({}), home=clean_home)
        assert report.exit_code == 0
        assert all(c.status is not CheckStatus.FAIL for c in report.checks)

    def test_node_conflict_warns(self, clean_home):
        (clean_home / ".nvm").mkdir()
        (clean_home / ".nvm" / "nvm.sh").write_text("")
        runner = FakeCommandRunner({"fnm": _ok("fnm", "fnm 1.35.0")})
        report = run_development_checks(runner=runner, home=clean_home)
        by_id = {c.id: c for c in report.checks}
        assert by_id["development_node_manager_conflict"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_node_single_non_fnm_manager_does_not_warn(self, clean_home):
        # Doctor's WARN threshold is specifically ">1 manager" (a real
        # conflict); a single non-fnm manager is the planner's BLOCKED
        # concern, not a doctor-level conflict - see
        # docs/development/node-strategy.md.
        runner = FakeCommandRunner({"mise": _ok("mise", "2024.1.0")})
        report = run_development_checks(runner=runner, home=clean_home)
        by_id = {c.id: c for c in report.checks}
        assert by_id["development_node_manager_conflict"].status is CheckStatus.PASS

    def test_container_conflict_warns(self, clean_home):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "docker": _ok("docker", "Docker version 25.0.0"),
        })
        report = run_development_checks(runner=runner, home=clean_home)
        by_id = {c.id: c for c in report.checks}
        assert by_id["development_container_engine_conflict"].status is CheckStatus.WARN

    def test_json_shape_matches_shared_doctor_report(self, clean_home):
        report = run_development_checks(runner=FakeCommandRunner({}), home=clean_home)
        data = report.to_dict()
        assert data["schema_version"] == 1
        assert set(data["summary"]) == {"PASS", "WARN", "FAIL", "SKIP"}
