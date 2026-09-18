"""Tests for the S6.5 Focus runtime executor (serein.focus.runtime,
Phase-7-completion Section 26-29).

Layer A only: every test runs against an injectable ``root``
(``tmp_path``) and a fake command runner - never the real host, never
real systemd, never a real cgroup.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from serein.development.runner import CommandResult
from serein.focus.models import RELATIVE_WEIGHTS
from serein.focus.runtime import (
    FOCUS_RUNTIME_STATE_RELATIVE_PATH,
    apply_focus_transition,
    read_focus_runtime_state,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


class FakeCommandRunner:
    def __init__(self, responses: dict[str, CommandResult | None] | None = None):
        self._responses = responses or {}
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):  # noqa: ANN001, ANN201
        self.calls.append(list(args))
        binary = args[0]
        if binary not in self._responses:
            return None
        return self._responses[binary]


class TestReadState:
    def test_missing_state_defaults_to_balanced(self, tmp_path: Path) -> None:
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "balanced"
        assert state.committed_at is None

    def test_corrupt_state_falls_back_safely(self, tmp_path: Path) -> None:
        path = tmp_path / FOCUS_RUNTIME_STATE_RELATIVE_PATH
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json", encoding="utf-8")
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "balanced"

    def test_unrecognized_active_focus_falls_back_safely(self, tmp_path: Path) -> None:
        path = tmp_path / FOCUS_RUNTIME_STATE_RELATIVE_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"active_focus": "not-a-real-target"}), encoding="utf-8")
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "balanced"


class TestNoopTransition:
    def test_same_focus_commits_without_writing_slices(self, tmp_path: Path) -> None:
        result = apply_focus_transition("balanced", tmp_path, FakeCommandRunner())
        assert result.status == "committed"
        assert result.from_focus == "balanced"
        assert result.to_focus == "balanced"
        assert result.slice_results == ()
        slice_dir = tmp_path / "etc" / "systemd" / "system"
        assert not slice_dir.exists() or not any(slice_dir.glob("serein*.slice"))


class TestRealTransition:
    def test_dev_transition_writes_expected_slices(self, tmp_path: Path) -> None:
        result = apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        assert result.status == "committed"
        assert result.from_focus == "balanced"
        assert result.to_focus == "dev"
        names = {r.slice_name for r in result.slice_results}
        assert names == {
            "serein.slice", "serein-dev.slice", "serein-ai.slice",
            "serein-cyber.slice", "serein-background.slice",
        }
        assert all(r.verified for r in result.slice_results)

    def test_serein_private_slice_name_never_appears_in_any_transition(
        self, tmp_path: Path
    ) -> None:
        # docs/focus/future-runtime.md: privacy correctness needs a
        # stronger boundary than a cgroup weight can provide - no
        # serein-private.slice is ever written, for any target.
        for target in ("dev", "ai", "cyber"):
            result = apply_focus_transition(target, tmp_path, FakeCommandRunner())
            names = {r.slice_name for r in result.slice_results}
            assert "serein-private.slice" not in names

    def test_private_focus_honors_its_own_readiness_gate(self, tmp_path: Path) -> None:
        # A bare fixture root has no real privacy-tooling evidence, so
        # the SAME planner used elsewhere honestly reports "private" as
        # blocked here - the runtime executor must never bypass that
        # gate and write anything regardless.
        result = apply_focus_transition("private", tmp_path, FakeCommandRunner())
        assert result.status == "blocked"
        assert result.slice_results == ()
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "balanced"

    def test_dev_slice_gets_primary_weight(self, tmp_path: Path) -> None:
        result = apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        dev_result = next(r for r in result.slice_results if r.slice_name == "serein-dev.slice")
        assert dev_result.cpu_weight == RELATIVE_WEIGHTS["primary"]
        assert dev_result.io_weight == RELATIVE_WEIGHTS["primary"]

    def test_non_primary_domain_gets_secondary_weight(self, tmp_path: Path) -> None:
        result = apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        ai_result = next(r for r in result.slice_results if r.slice_name == "serein-ai.slice")
        assert ai_result.cpu_weight == RELATIVE_WEIGHTS["secondary"]

    def test_background_and_parent_slices_have_no_explicit_weight(
        self, tmp_path: Path
    ) -> None:
        result = apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        for name in ("serein.slice", "serein-background.slice"):
            r = next(x for x in result.slice_results if x.slice_name == name)
            assert r.cpu_weight is None
            assert r.io_weight is None

    def test_gpu_always_reported_not_enforceable(self, tmp_path: Path) -> None:
        result = apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        assert "NOT_ENFORCEABLE" in result.gpu_note

    def test_commit_persists_state_readable_back(self, tmp_path: Path) -> None:
        apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "dev"
        assert state.committed_at is not None

    def test_second_transition_moves_from_the_persisted_state(self, tmp_path: Path) -> None:
        apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        result = apply_focus_transition("ai", tmp_path, FakeCommandRunner())
        assert result.from_focus == "dev"
        assert result.to_focus == "ai"
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "ai"

    def test_never_writes_a_user_slice_only_system(self, tmp_path: Path) -> None:
        apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        assert (tmp_path / "etc" / "systemd" / "system" / "serein-dev.slice").is_file()
        assert not (tmp_path / "etc" / "systemd" / "user").exists()


class TestUnknownTarget:
    def test_unknown_target_fails_without_writing_anything(self, tmp_path: Path) -> None:
        result = apply_focus_transition("not-a-real-target", tmp_path, FakeCommandRunner())
        assert result.status == "failed"
        assert result.slice_results == ()
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "balanced"


class TestRollbackOnWriteFailure:
    def test_unwritable_slice_dir_rolls_back_without_persisting(self, tmp_path: Path) -> None:
        # Pre-create the target slice-unit directory's PARENT as a file,
        # not a directory, so mkdir(parents=True) fails for the unit dir.
        systemd_dir = tmp_path / "etc" / "systemd"
        systemd_dir.mkdir(parents=True)
        blocker = systemd_dir / "system"
        blocker.write_text("not a directory", encoding="utf-8")

        result = apply_focus_transition("dev", tmp_path, FakeCommandRunner())
        assert result.status in ("rolled_back", "failed")
        state = read_focus_runtime_state(tmp_path)
        assert state.active_focus == "balanced"


class TestSchema:
    def test_schema_file_is_valid_json_schema(self) -> None:
        schema = _load_schema("focus-runtime-state.schema.json")
        jsonschema.Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize("target", ["balanced", "dev", "ai", "private"])
    def test_persisted_state_validates_against_schema(
        self, tmp_path: Path, target: str
    ) -> None:
        apply_focus_transition(target, tmp_path, FakeCommandRunner())
        schema = _load_schema("focus-runtime-state.schema.json")
        state_path = tmp_path / FOCUS_RUNTIME_STATE_RELATIVE_PATH
        if state_path.is_file():
            instance = json.loads(state_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=instance, schema=schema)
        else:
            # "private" against a bare fixture is BLOCKED and never
            # persists anything - nothing to validate, and that is
            # itself the correct behavior (see TestRealTransition).
            assert target == "private"
