"""Tests for the Serein branding/identity foundation (Phase-7-completion
Section 9/14, S7.2 asset-handoff contract Section 5/13)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from serein.branding.fastfetch import (
    FOCUS_LABEL_COMMAND,
    build_fastfetch_config,
    focus_display_label,
)
from serein.branding.manifest import ASSETS, missing_assets, pending_asset_requests
from serein.branding.os_identity import render_issue, render_issue_net, render_os_release
from serein.branding.tokens import load_design_tokens
from serein.desktop.models import TARGET_UBUNTU_VERSION
from serein.distribution.payload import PAYLOAD_RESOURCE_ROOTS, collect_resource_entries
from serein.focus.runtime import apply_focus_transition
from serein.hardware.os_release import read_os_release

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


class _FakeCommandRunner:
    def run(self, args, timeout: float = 3.0):  # noqa: ANN001, ANN201
        return None


class TestDesignTokens:
    def test_loads_from_the_real_repository_file(self) -> None:
        tokens = load_design_tokens()
        assert tokens.design_language == "Quiet Velocity"
        assert tokens.core_values == ("Quiet", "Fast", "Focused", "Adaptive")

    def test_validates_against_schema(self) -> None:
        tokens = load_design_tokens()
        schema = _load_schema("design-tokens.schema.json")
        jsonschema.validate(instance=tokens.to_dict(), schema=schema)

    @pytest.mark.parametrize(
        "name,expected_hex",
        [
            ("background", "#0D1117"),
            ("surface", "#151B23"),
            ("elevated", "#1C2430"),
            ("primary", "#75BFD8"),
            ("secondary", "#91A7B4"),
            ("focus", "#A6DCEF"),
            ("text", "#DCE6EC"),
            ("muted", "#81909A"),
        ],
    )
    def test_pinned_palette_values(self, name: str, expected_hex: str) -> None:
        tokens = load_design_tokens()
        assert tokens.color(name).hex == expected_hex

    def test_unknown_color_raises(self) -> None:
        tokens = load_design_tokens()
        with pytest.raises(KeyError):
            tokens.color("not-a-real-token")

    def test_visual_ratio_sums_to_one(self) -> None:
        tokens = load_design_tokens()
        total = (
            tokens.visual_ratio.neutral
            + tokens.visual_ratio.accent
            + tokens.visual_ratio.focus_status
        )
        assert total == pytest.approx(1.0)


class TestAssetManifest:
    def test_no_shipped_asset_is_missing_from_disk(self) -> None:
        assert missing_assets() == []

    def test_every_asset_id_is_unique(self) -> None:
        ids = [a.id for a in ASSETS]
        assert len(ids) == len(set(ids))

    def test_pending_assets_have_no_file_on_disk_yet(self) -> None:
        # The whole point of "pending_asset_request" is honesty: no
        # placeholder has been silently committed under its name.
        for asset in pending_asset_requests():
            assert not (REPO_ROOT / asset.repo_path).exists(), (
                f"{asset.id} is marked pending_asset_request but a file "
                f"already exists at {asset.repo_path} - either the asset "
                "was provided (flip status to shipped) or a placeholder "
                "was committed by mistake (Section 13: never commit one)."
            )

    def test_derivative_assets_name_a_real_source_asset(self) -> None:
        ids = {a.id for a in ASSETS}
        for asset in ASSETS:
            if asset.derived_from is not None:
                assert asset.derived_from in ids

    def test_pending_master_logo_and_wallpaper_are_the_two_real_requests(self) -> None:
        pending_ids = {a.id for a in pending_asset_requests()}
        assert "serein-logo-primary" in pending_ids
        assert "serein-wallpaper-default-dark" in pending_ids


class TestTerminalMark:
    def test_ascii_mark_exists_and_is_narrow_enough_for_any_terminal(self) -> None:
        path = REPO_ROOT / "branding" / "terminal" / "serein-mark.txt"
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert text.strip()
        for line in text.splitlines():
            assert len(line) <= 80

    def test_contains_the_wordmark_and_tagline(self) -> None:
        path = REPO_ROOT / "branding" / "terminal" / "serein-mark.txt"
        text = path.read_text(encoding="utf-8")
        assert "SEREIN" in text.replace(" ", "")
        assert "quiet velocity" in text.lower()

    def test_no_literal_s_character_pasted_inside_the_mark_glyph(self) -> None:
        # Section 12/4: the mark itself (before the wordmark line) must
        # not fake recognition with a literal typed "S" - only ASCII
        # line-drawing characters.
        path = REPO_ROOT / "branding" / "terminal" / "serein-mark.txt"
        text = path.read_text(encoding="utf-8")
        glyph_lines = text.split("\n\n")[0]
        assert "s" not in glyph_lines.lower()


class TestPayloadWiring:
    def test_branding_is_a_payload_resource_root(self) -> None:
        assert "branding" in PAYLOAD_RESOURCE_ROOTS

    def test_shipped_branding_files_are_collected(self) -> None:
        entries = collect_resource_entries(roots=("branding",))
        paths = {e.path for e in entries}
        assert "branding/tokens/design-tokens.json" in paths
        assert "branding/terminal/serein-mark.txt" in paths

    def test_pending_asset_files_are_never_collected(self) -> None:
        # They don't exist on disk at all yet, so this is really just
        # confirming collect_resource_entries only ever walks real files.
        entries = collect_resource_entries(roots=("branding",))
        paths = {e.path for e in entries}
        for asset in pending_asset_requests():
            assert asset.repo_path not in paths


class TestOSIdentity:
    def test_os_release_round_trips_through_the_real_reader(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text(render_os_release(), encoding="utf-8")
        info = read_os_release(tmp_path)
        assert info.id == "serein"
        assert info.pretty_name == "Serein OS"
        assert info.version_id == TARGET_UBUNTU_VERSION

    def test_id_like_ubuntu_makes_is_ubuntu_true(self, tmp_path: Path) -> None:
        # The exact real-world correctness fix this module required:
        # a Serein system (ID=serein) must still count as
        # Ubuntu-compatible via ID_LIKE, not just a literal ID=ubuntu.
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text(render_os_release(), encoding="utf-8")
        info = read_os_release(tmp_path)
        assert "ubuntu" in info.id_like
        assert info.is_ubuntu is True

    def test_never_claims_independence_from_ubuntu(self) -> None:
        text = render_os_release()
        assert "ID_LIKE=ubuntu" in text
        assert f'VERSION_ID="{TARGET_UBUNTU_VERSION}"' in text

    def test_issue_uses_real_getty_escape_sequences(self) -> None:
        text = render_issue()
        assert "\\n" in text
        assert "\\l" in text
        assert "Serein OS" in text

    def test_issue_net_is_plain_text_no_escape_sequences(self) -> None:
        text = render_issue_net()
        assert "\\n" not in text
        assert "\\l" not in text
        assert text.strip() == "Serein OS"


class TestFastfetch:
    def test_config_is_valid_json(self) -> None:
        config = build_fastfetch_config()
        # Must round-trip through json.dumps/loads cleanly - the real
        # syntax check available without a real fastfetch binary
        # (Section 82 - never claim more than that).
        json.loads(json.dumps(config))

    def test_logo_is_file_type_never_requires_image_protocol(self) -> None:
        config = build_fastfetch_config()
        assert config["logo"]["type"] == "file"

    def test_no_module_requires_sixel_or_kitty_graphics(self) -> None:
        config = build_fastfetch_config()
        text = json.dumps(config).lower()
        assert "sixel" not in text
        assert "kitty" not in text
        assert "iterm" not in text

    def test_focus_and_mode_modules_present(self) -> None:
        config = build_fastfetch_config()
        keys = {m.get("key") for m in config["modules"] if isinstance(m, dict)}
        assert "Focus" in keys
        assert "Mode" in keys

    def test_focus_module_shells_out_to_the_same_command_the_cli_entrypoint_uses(
        self,
    ) -> None:
        config = build_fastfetch_config()
        focus_module = next(
            m for m in config["modules"] if isinstance(m, dict) and m.get("key") == "Focus"
        )
        assert focus_module["text"] == FOCUS_LABEL_COMMAND

    def test_focus_label_defaults_to_default_with_no_committed_transition(
        self, tmp_path: Path
    ) -> None:
        assert focus_display_label(tmp_path) == "Default"

    def test_focus_label_reflects_a_real_committed_transition(self, tmp_path: Path) -> None:
        apply_focus_transition("dev", tmp_path, _FakeCommandRunner())
        assert focus_display_label(tmp_path) == "Development"


class TestBrandingMainEntrypoint:
    def test_focus_label_prints_a_single_line(self, capsys) -> None:
        from serein.branding.__main__ import main

        exit_code = main(["focus-label"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out.strip() == "Default"

    def test_unknown_command_exits_nonzero(self) -> None:
        from serein.branding.__main__ import main

        with pytest.raises(SystemExit) as excinfo:
            main(["not-a-real-command"])
        assert excinfo.value.code != 0
