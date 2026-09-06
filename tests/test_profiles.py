"""Profile manifest and registry tests."""

from __future__ import annotations

import json
from pathlib import Path

from serein.profiles.models import ProfileManifest
from serein.profiles.registry import DECLARED_ONLY_PROFILES, list_profiles

REPO_ROOT = Path(__file__).resolve().parents[1]

_S2_HARDWARE_PROFILES = ("balanced", "dev", "ai", "battery", "cyber")


class TestManifestParsing:
    def test_core_manifest_round_trips(self):
        data = json.loads((REPO_ROOT / "profiles" / "core" / "core.profile.json").read_text())
        manifest = ProfileManifest.from_dict(data)
        assert manifest.id == "core"
        assert manifest.status == "implemented"
        assert manifest.rollback.supported is False

    def test_missing_optional_fields_default_to_empty(self):
        manifest = ProfileManifest.from_dict(
            {
                "schema_version": 1,
                "id": "minimal",
                "name": "Minimal",
                "version": "0.1.0",
                "status": "declared",
                "description": "test",
            }
        )
        assert manifest.packages == []
        assert manifest.rollback.supported is False
        assert manifest.rollback.notes is None


class TestRegistryDefaults:
    def test_core_is_implemented(self):
        profiles = {p.id: p for p in list_profiles()}
        assert profiles["core"].status == "implemented"
        assert profiles["core"].active is False

    def test_declared_only_identities_present(self):
        profiles = {p.id: p for p in list_profiles()}
        for declared in DECLARED_ONLY_PROFILES:
            assert profiles[declared.id].status == "declared"
            assert profiles[declared.id].active is False

    def test_nothing_is_ever_active_in_s0(self):
        assert all(not p.active for p in list_profiles())


class TestRegistryIsolation:
    def test_empty_directory_falls_back_to_declared_only(self, tmp_path):
        profiles = {p.id: p for p in list_profiles(profiles_dir=tmp_path)}
        assert "core" not in profiles
        for declared in DECLARED_ONLY_PROFILES:
            assert profiles[declared.id].status == "declared"

    def test_malformed_manifest_is_skipped_not_raised(self, tmp_path):
        bad_dir = tmp_path / "broken"
        bad_dir.mkdir()
        (bad_dir / "broken.profile.json").write_text("{not valid json")
        # must not raise
        profiles = list_profiles(profiles_dir=tmp_path)
        assert isinstance(profiles, list)

    def test_manifest_overrides_declared_only_stub(self, tmp_path):
        custom_dir = tmp_path / "dev"
        custom_dir.mkdir()
        (custom_dir / "dev.profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "dev",
                    "name": "Development (custom)",
                    "version": "0.0.1",
                    "status": "implemented",
                    "description": "overrides the declared-only stub",
                }
            )
        )
        profiles = {p.id: p for p in list_profiles(profiles_dir=tmp_path)}
        assert profiles["dev"].status == "implemented"
        assert profiles["dev"].name == "Development (custom)"

    def test_nonexistent_directory_does_not_raise(self, tmp_path):
        profiles = list_profiles(profiles_dir=tmp_path / "does-not-exist")
        assert len(profiles) == len(DECLARED_ONLY_PROFILES)


class TestS2HardwareProfileManifests:
    """balanced/dev/ai/battery/cyber gained real manifests in S2 — their
    hardware resource-policy layer, not their S3/S4/S5 application layer."""

    def test_all_five_have_manifests_and_are_implemented(self):
        profiles = {p.id: p for p in list_profiles()}
        for profile_id in _S2_HARDWARE_PROFILES:
            assert profiles[profile_id].status == "implemented"
            assert profiles[profile_id].active is False

    def test_all_five_round_trip_through_manifest_model(self):
        for profile_id in _S2_HARDWARE_PROFILES:
            path = REPO_ROOT / "profiles" / profile_id / f"{profile_id}.profile.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            manifest = ProfileManifest.from_dict(data)
            assert manifest.id == profile_id
            assert manifest.dependencies == ["core"]
            assert "power-profiles-daemon" in manifest.packages
            assert "systemd-zram-generator" in manifest.packages
            assert manifest.rollback.supported is False

    def test_only_battery_declares_a_battery_hardware_condition(self):
        for profile_id in _S2_HARDWARE_PROFILES:
            path = REPO_ROOT / "profiles" / profile_id / f"{profile_id}.profile.json"
            manifest = ProfileManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if profile_id == "battery":
                assert manifest.hardware_conditions == ["battery_present"]
            else:
                assert manifest.hardware_conditions == []
