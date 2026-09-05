"""Profile manifest and registry tests."""

from __future__ import annotations

import json
from pathlib import Path

from serein.profiles.models import ProfileManifest
from serein.profiles.registry import DECLARED_ONLY_PROFILES, list_profiles

REPO_ROOT = Path(__file__).resolve().parents[1]


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
