"""Desktop subsystem tests. Every filesystem-facing case uses a fixture
root under tests/fixtures/hosts/ — never the real host. Session detection
uses plain dict literals for `env` — never the real process environment."""

from __future__ import annotations

import json
from pathlib import Path

from serein.desktop.config import RESOURCES, missing_resources, repo_root
from serein.desktop.detect import detect_availability, detect_config_state, detect_session
from serein.desktop.doctor import run_desktop_checks
from serein.desktop.models import DESKTOP_CONFIG_VERSION
from serein.desktop.models import SCHEMA_VERSION as DESKTOP_SCHEMA_VERSION
from serein.desktop.packages import all_packages
from serein.desktop.plan import build_desktop_plan
from serein.desktop.status import build_desktop_status
from serein.doctor.models import CheckStatus
from serein.profiles.models import ProfileManifest
from serein.profiles.registry import list_profiles

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPackages:
    def test_all_packages_deduplicated_and_sorted(self):
        packages = all_packages()
        assert packages == sorted(set(packages))

    def test_excludes_x11_session_and_kitchen_sink(self):
        packages = all_packages()
        assert "plasma-session-x11" not in packages
        assert "kubuntu-desktop" not in packages

    def test_includes_core_expected_components(self):
        packages = all_packages()
        for expected in ("plasma-desktop", "sddm", "dolphin", "konsole", "kwin-wayland"):
            assert expected in packages


class TestConfigResources:
    def test_all_declared_resources_exist_in_repo(self):
        assert missing_resources() == []

    def test_repo_root_resolves_to_actual_checkout(self):
        assert (repo_root() / "pyproject.toml").is_file()

    def test_resource_ids_are_unique(self):
        ids = [r.id for r in RESOURCES]
        assert len(ids) == len(set(ids))


class TestDetectAvailability:
    def test_plasma_wayland_fixture(self, host_root):
        availability = detect_availability(host_root("plasma_wayland"))
        assert availability.plasma_installed is True
        assert availability.kwin_wayland_installed is True
        assert availability.kwin_x11_installed is False
        assert availability.sddm_installed is True

    def test_plasma_x11_fixture(self, host_root):
        availability = detect_availability(host_root("plasma_x11"))
        assert availability.kwin_wayland_installed is False
        assert availability.kwin_x11_installed is True

    def test_no_plasma_on_plain_host(self, host_root):
        availability = detect_availability(host_root("amd_desktop"))
        assert availability.plasma_installed is False
        assert availability.sddm_installed is False

    def test_missing_data_never_raises(self, host_root):
        availability = detect_availability(host_root("missing_data"))
        assert availability.plasma_installed is False


class TestDetectSession:
    def test_wayland_session(self):
        session = detect_session({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"})
        assert session.session_type == "wayland"
        assert session.desktop_environment == "KDE"

    def test_x11_session(self):
        session = detect_session({"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE"})
        assert session.session_type == "x11"

    def test_no_session_env_at_all(self):
        session = detect_session({})
        assert session.session_type is None
        assert session.desktop_environment is None

    def test_non_kde_desktop_reported_as_none(self):
        session = detect_session({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"})
        assert session.desktop_environment is None

    def test_garbage_session_type_ignored(self):
        session = detect_session({"XDG_SESSION_TYPE": "mir"})
        assert session.session_type is None


class TestDetectConfigState:
    def test_managed_host_reports_applied(self, host_root):
        state = detect_config_state(host_root("plasma_wayland_managed"))
        assert state.serein_preset_applied is True
        assert state.desktop_config_version == 1

    def test_unmanaged_host_reports_not_applied(self, host_root):
        state = detect_config_state(host_root("plasma_wayland"))
        assert state.serein_preset_applied is False
        assert state.desktop_config_version is None

    def test_missing_data_reports_not_applied_not_error(self, host_root):
        state = detect_config_state(host_root("missing_data"))
        assert state.serein_preset_applied is False


class TestDesktopPlan:
    def test_deterministic(self):
        assert build_desktop_plan().to_dict() == build_desktop_plan().to_dict()

    def test_packages_match_packages_module(self):
        plan = build_desktop_plan()
        assert plan.packages == all_packages()

    def test_records_config_version(self):
        plan = build_desktop_plan()
        joined = " ".join(step.detail for step in plan.system_configuration)
        assert str(DESKTOP_CONFIG_VERSION) in joined

    def test_schema_version(self):
        assert build_desktop_plan().schema_version == DESKTOP_SCHEMA_VERSION

    def test_to_dict_is_json_serializable(self):
        assert json.dumps(build_desktop_plan().to_dict())


class TestDesktopStatus:
    def test_plasma_wayland_managed(self, host_root):
        status = build_desktop_status(
            root=host_root("plasma_wayland_managed"),
            env={"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"},
        )
        assert status.availability.plasma_installed is True
        assert status.session.session_type == "wayland"
        assert status.config.serein_preset_applied is True
        assert status.os_compatibility == "supported"

    def test_plain_host_reports_honest_unavailable(self, host_root):
        status = build_desktop_status(root=host_root("amd_desktop"), env={})
        assert status.availability.plasma_installed is False
        assert status.session.session_type is None
        assert status.config.serein_preset_applied is False

    def test_profile_status_reflects_registry(self, host_root):
        status = build_desktop_status(root=host_root("missing_data"), env={})
        assert status.profile_status == "implemented"

    def test_missing_data_never_raises(self, host_root):
        status = build_desktop_status(root=host_root("missing_data"), env={})
        assert status.profile_id == "desktop"


class TestDesktopDoctor:
    def test_unmanaged_and_uninstalled_is_skip(self, host_root):
        report = run_desktop_checks(host_root("amd_desktop"), env={})
        by_id = {c.id: c for c in report.checks}
        assert by_id["desktop_plasma_availability"].status is CheckStatus.SKIP
        assert by_id["desktop_kwin_availability"].status is CheckStatus.SKIP
        assert by_id["desktop_sddm_availability"].status is CheckStatus.SKIP

    def test_installed_but_unmanaged_is_warn(self, host_root):
        report = run_desktop_checks(host_root("plasma_wayland"), env={})
        by_id = {c.id: c for c in report.checks}
        assert by_id["desktop_plasma_availability"].status is CheckStatus.WARN
        assert by_id["desktop_sddm_availability"].status is CheckStatus.WARN

    def test_managed_and_installed_is_pass(self, host_root):
        report = run_desktop_checks(host_root("plasma_wayland_managed"), env={})
        by_id = {c.id: c for c in report.checks}
        assert by_id["desktop_plasma_availability"].status is CheckStatus.PASS
        assert by_id["desktop_sddm_availability"].status is CheckStatus.PASS

    def test_managed_but_missing_component_is_fail(self, host_root):
        report = run_desktop_checks(host_root("broken_desktop_install"), env={})
        by_id = {c.id: c for c in report.checks}
        assert by_id["desktop_plasma_availability"].status is CheckStatus.FAIL
        assert by_id["desktop_kwin_availability"].status is CheckStatus.FAIL
        assert by_id["desktop_sddm_availability"].status is CheckStatus.FAIL
        assert report.exit_code == 1

    def test_wayland_session_pass_x11_warn_none_skip(self, host_root):
        root = host_root("amd_desktop")
        wayland = run_desktop_checks(root, env={"XDG_SESSION_TYPE": "wayland"})
        x11 = run_desktop_checks(root, env={"XDG_SESSION_TYPE": "x11"})
        headless = run_desktop_checks(root, env={})

        def status_for(report, check_id):
            return next(c.status for c in report.checks if c.id == check_id)

        assert status_for(wayland, "desktop_wayland_session") is CheckStatus.PASS
        assert status_for(x11, "desktop_wayland_session") is CheckStatus.WARN
        assert status_for(headless, "desktop_wayland_session") is CheckStatus.SKIP

    def test_config_contract_and_resources_pass_against_real_repo(self, host_root):
        report = run_desktop_checks(host_root("missing_data"), env={})
        by_id = {c.id: c for c in report.checks}
        assert by_id["desktop_config_contract"].status is CheckStatus.PASS
        assert by_id["desktop_required_resources"].status is CheckStatus.PASS

    def test_json_shape_matches_foundation_doctor_report(self, host_root):
        report = run_desktop_checks(host_root("amd_desktop"), env={})
        data = report.to_dict()
        assert data["schema_version"] == 1
        assert set(data["summary"]) == {"PASS", "WARN", "FAIL", "SKIP"}


class TestDesktopProfileConsistency:
    """The manifest must never silently drift from the code that
    describes what it claims to install."""

    def _manifest(self) -> ProfileManifest:
        data = json.loads((REPO_ROOT / "profiles" / "desktop" / "desktop.profile.json").read_text())
        return ProfileManifest.from_dict(data)

    def test_manifest_packages_match_packages_module(self):
        assert sorted(self._manifest().packages) == all_packages()

    def test_manifest_configuration_units_match_config_resources(self):
        assert set(self._manifest().configuration_units) == {r.id for r in RESOURCES}

    def test_manifest_status_is_implemented(self):
        assert self._manifest().status == "implemented"

    def test_desktop_is_implemented_in_registry(self):
        profiles = {p.id: p for p in list_profiles()}
        assert profiles["desktop"].status == "implemented"
        assert profiles["core"].status == "implemented"
        for declared_id in ("balanced", "battery", "dev", "ai", "cyber"):
            assert profiles[declared_id].status == "declared"
