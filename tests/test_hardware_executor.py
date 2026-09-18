"""Tests for the S2 hardware apply engine (serein.hardware.executor,
Phase-7-completion Section 25).

Layer A only: every test runs against an injectable ``root``
(``tmp_path``) and a fake command runner - never the real host, never
real sysfs, never a real ``powerprofilesctl``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serein.development.runner import CommandResult
from serein.hardware.executor import ActionResult, apply_hardware_plan
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.models import HardwarePlan, PlanAction
from serein.hardware.planner import build_hardware_plan

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _plan(*actions: PlanAction) -> HardwarePlan:
    return HardwarePlan(
        schema_version=1, profile_id="balanced", profile_available=True,
        unavailable_reason=None, actions=list(actions),
    )


def _action(action: str, status: str, target: str | None = "balanced",
            current: str | None = None, reversible: bool = True) -> PlanAction:
    return PlanAction(
        id=f"test.{action}", component="test", action=action, target=target,
        current=current, reason="test fixture", confidence="high",
        requires_root=True, reversible=reversible, risk="low",
        verification="n/a", status=status,
    )


class TestNonApplyActionsPassThrough:
    @pytest.mark.parametrize("status", ["NOOP", "SKIP", "BLOCKED"])
    def test_recorded_verbatim_never_attempted(self, tmp_path: Path, status: str) -> None:
        plan = _plan(_action("set_power_profile", status))
        results = apply_hardware_plan(plan, tmp_path, FakeCommandRunner())
        assert len(results) == 1
        assert results[0].status == status.lower()
        assert results[0].changed is False


class TestUnimplementedAction:
    def test_apply_action_with_no_implementation_is_not_enforceable(
        self, tmp_path: Path
    ) -> None:
        plan = _plan(_action("set_epp", "APPLY"))
        results = apply_hardware_plan(plan, tmp_path, FakeCommandRunner())
        assert results[0].status == "not_enforceable"
        assert results[0].changed is False


class TestPowerProfileApply:
    def test_successful_apply_verifies_via_get(self, tmp_path: Path) -> None:
        runner = FakeCommandRunner({
            "powerprofilesctl": CommandResult(0, "balanced\n", ""),
        })
        plan = _plan(_action("set_power_profile", "APPLY", target="balanced"))
        results = apply_hardware_plan(plan, tmp_path, runner)
        result = results[0]
        assert result.status == "applied"
        assert result.changed is True
        assert result.verified is True
        assert runner.calls == [
            ["powerprofilesctl", "set", "balanced"],
            ["powerprofilesctl", "get"],
        ]

    def test_set_failure_never_calls_get(self, tmp_path: Path) -> None:
        runner = FakeCommandRunner({
            "powerprofilesctl": CommandResult(1, "", "no such profile"),
        })
        plan = _plan(_action("set_power_profile", "APPLY", target="balanced"))
        result = apply_hardware_plan(plan, tmp_path, runner)[0]
        assert result.status == "failed"
        assert result.verified is False
        assert runner.calls == [["powerprofilesctl", "set", "balanced"]]

    def test_binary_missing_reported_failed_not_crashed(self, tmp_path: Path) -> None:
        plan = _plan(_action("set_power_profile", "APPLY", target="balanced"))
        result = apply_hardware_plan(plan, tmp_path, FakeCommandRunner())[0]
        assert result.status == "failed"
        assert result.changed is False

    def test_verify_mismatch_is_failed_despite_zero_exit(self, tmp_path: Path) -> None:
        runner = FakeCommandRunner({
            "powerprofilesctl": CommandResult(0, "power-saver\n", ""),
        })
        plan = _plan(_action("set_power_profile", "APPLY", target="balanced"))
        result = apply_hardware_plan(plan, tmp_path, runner)[0]
        assert result.status == "failed"
        assert result.verified is False


class TestZramApply:
    def test_writes_pinned_default_to_confd_never_base_file(self, tmp_path: Path) -> None:
        plan = _plan(_action("configure_zram", "APPLY", target="pinned default", current=None))
        result = apply_hardware_plan(plan, tmp_path, FakeCommandRunner(), repo_root=REPO_ROOT)[0]
        assert result.status == "applied"
        assert result.changed is True
        assert result.verified is True

        confd_target = tmp_path / "etc" / "systemd" / "zram-generator.conf.d" / "90-serein.conf"
        assert confd_target.is_file()
        base_file = tmp_path / "etc" / "systemd" / "zram-generator.conf"
        assert not base_file.exists()

        pinned = (REPO_ROOT / "hardware" / "defaults" / "zram-generator.conf").read_text(
            encoding="utf-8"
        )
        assert confd_target.read_text(encoding="utf-8") == pinned

    def test_verification_reuses_existing_memory_policy_detector(self, tmp_path: Path) -> None:
        plan = _plan(_action("configure_zram", "APPLY", target="pinned default", current=None))
        apply_hardware_plan(plan, tmp_path, FakeCommandRunner(), repo_root=REPO_ROOT)
        policy = detect_memory_policy(tmp_path)
        assert policy.zram_generator_config_sources


class TestEndToEndWiring:
    def test_real_planner_output_feeds_executor_without_crashing(
        self, tmp_path: Path
    ) -> None:
        # No hardware evidence in an empty tmp_path root - every action
        # should legitimately come back SKIP/BLOCKED (never APPLY with
        # no evidence), proving the executor's own dispatch never
        # crashes on a real HardwarePlan shape.
        plan = build_hardware_plan("balanced", tmp_path)
        results = apply_hardware_plan(plan, tmp_path, FakeCommandRunner())
        assert len(results) == len(plan.actions)
        assert all(isinstance(r, ActionResult) for r in results)
        assert all(r.status != "applied" for r in results)
