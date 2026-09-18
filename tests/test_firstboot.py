"""Tests for the First-Boot Provisioning subsystem (S7.2).

Layer A only: every test runs against an injectable fixture root
(``tmp_path``) and a fake command runner - never a real installed
system, never real systemd. Real S7.2 runtime validation (boot an
S7.1-installed qcow2 under OVMF, run the real systemd unit, prove a
second boot does not re-provision) is Layer B and is deferred - see
``docs/firstboot/known-limitations.md``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import jsonschema
import pytest

from serein.desktop.config import RESOURCES as DESKTOP_RESOURCES
from serein.development.runner import CommandResult
from serein.firstboot.atomic import atomic_write_json
from serein.firstboot.doctor import run_firstboot_checks
from serein.firstboot.eligibility import evaluate_eligibility
from serein.firstboot.engine import _record_first_failure, run_firstboot
from serein.firstboot.installstate import read_install_state
from serein.firstboot.livemedia import detect_live_media
from serein.firstboot.lock import FirstbootLock, is_lock_held
from serein.firstboot.models import (
    FIRSTBOOT_EVIDENCE_RELATIVE_PATH,
    FIRSTBOOT_LOCK_RELATIVE_PATH,
    FIRSTBOOT_STATE_RELATIVE_PATH,
    STEP_IDS,
    FirstbootState,
)
from serein.firstboot.plan import build_firstboot_plan
from serein.firstboot.statefile import FirstbootStateStore
from serein.firstboot.status import build_firstboot_status
from serein.firstboot.steps import DEFAULT_STEPS, StepDefinition, StepOutcome
from serein.installer.payload import build_install_state_marker

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
SOURCE_COMMIT = "a" * 40


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


class FakeCommandRunner:
    """Maps a binary name to a canned CommandResult (or None = "not
    found"). Mirrors ``tests/test_development.py``'s ``FakeCommandRunner``
    exactly, so every S1-S6.5 status detector this subsystem reuses
    degrades the same honest way it already does in its own test suite."""

    def __init__(self, responses: dict[str, CommandResult | None] | None = None):
        self._responses = responses or {}
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):  # noqa: ANN001, ANN201
        self.calls.append(list(args))
        binary = args[0]
        if binary not in self._responses:
            return None
        return self._responses[binary]


def _install_state_path(root: Path) -> Path:
    return root / "etc" / "serein" / "install-state.json"


def _stage_system_desktop_resources(root: Path) -> None:
    """Mimics what a real package/install-time staging step (not yet
    implemented - SEREIN-DESKTOP-STAGING-PENDING) would have already
    done before first-boot ever runs: place every ``owner="system"``
    desktop resource at its real target path. Content fidelity is
    desktop's own test suite's concern (test_desktop.py); first-boot's
    ``step_desktop_baseline`` only ever checks presence."""
    for resource in DESKTOP_RESOURCES:
        if resource.owner != "system":
            continue
        target = root / resource.target_path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# staged for test: {resource.id}\n", encoding="utf-8")


def _write_valid_install_state(
    root: Path, *, firstboot_provisioning: str = "pending", source_commit: str = SOURCE_COMMIT
) -> None:
    marker = build_install_state_marker(
        source_commit=source_commit, source_media_version="26.04.1"
    )
    if firstboot_provisioning != "pending":
        marker = dataclasses.replace(marker, firstboot_provisioning=firstboot_provisioning)
    path = _install_state_path(root)
    atomic_write_json(path, marker.to_dict())
    _stage_system_desktop_resources(root)


def _write_raw_install_state(root: Path, data: dict) -> None:
    path = _install_state_path(root)
    atomic_write_json(path, data)


# --------------------------------------------------------------------------
# Install-state consumption (Section 5, 33-34)
# --------------------------------------------------------------------------


class TestInstallStateConsumption:
    def test_missing_is_reported_honestly(self, tmp_path: Path) -> None:
        result = read_install_state(tmp_path)
        assert result.present is False
        assert result.valid is False
        assert result.marker is None
        assert result.error == "missing"

    def test_malformed_json_never_raises(self, tmp_path: Path) -> None:
        path = _install_state_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json", encoding="utf-8")
        result = read_install_state(tmp_path)
        assert result.present is True
        assert result.valid is False
        assert result.marker is None
        assert result.error is not None and "malformed_json" in result.error

    def test_wrong_schema_version_is_rejected(self, tmp_path: Path) -> None:
        _write_raw_install_state(
            tmp_path,
            {
                "schema_version": 2, "phase": "s7.1", "installation_complete": True,
                "firstboot_provisioning": "pending", "source_media_version": "x",
                "source_commit": SOURCE_COMMIT,
            },
        )
        result = read_install_state(tmp_path)
        assert result.valid is False
        assert "schema_mismatch" in (result.error or "")

    def test_wrong_type_is_rejected(self, tmp_path: Path) -> None:
        _write_raw_install_state(
            tmp_path,
            {
                "schema_version": 1, "phase": "s7.1", "installation_complete": "yes",
                "firstboot_provisioning": "pending", "source_media_version": "x",
                "source_commit": SOURCE_COMMIT,
            },
        )
        result = read_install_state(tmp_path)
        assert result.valid is False

    def test_valid_marker_round_trips(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        result = read_install_state(tmp_path)
        assert result.valid is True
        assert result.marker is not None
        assert result.marker.firstboot_provisioning == "pending"
        assert result.marker.source_commit == SOURCE_COMMIT


# --------------------------------------------------------------------------
# Live-media detection (Section 10)
# --------------------------------------------------------------------------


class TestLiveMediaDetection:
    def test_clean_root_is_not_live(self, tmp_path: Path) -> None:
        evidence = detect_live_media(tmp_path)
        assert evidence.is_live_media is False

    def test_cmdline_casper_is_live(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        proc.mkdir()
        (proc / "cmdline").write_text("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash")
        evidence = detect_live_media(tmp_path)
        assert evidence.is_live_media is True
        assert evidence.cmdline_indicates_live is True
        assert evidence.reasons

    def test_overlay_root_fs_is_live(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        proc.mkdir()
        (proc / "mounts").write_text("overlay / overlay rw,relatime 0 0\n")
        evidence = detect_live_media(tmp_path)
        assert evidence.is_live_media is True
        assert evidence.overlay_root_fs is True

    def test_single_weak_signal_alone_is_not_live(self, tmp_path: Path) -> None:
        (tmp_path / "cdrom").mkdir()
        evidence = detect_live_media(tmp_path)
        assert evidence.is_live_media is False

    def test_two_weak_signals_together_are_live(self, tmp_path: Path) -> None:
        (tmp_path / "etc").mkdir()
        (tmp_path / "etc" / "casper.conf").write_text("export USERNAME=serein-user\n")
        (tmp_path / "run" / "live").mkdir(parents=True)
        evidence = detect_live_media(tmp_path)
        assert evidence.is_live_media is True
        assert evidence.casper_conf_present is True
        assert evidence.live_run_dir_present is True


# --------------------------------------------------------------------------
# Eligibility gate (Section 5, 33-37)
# --------------------------------------------------------------------------


class TestEligibility:
    def test_eligible_when_valid_and_pending(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        result = evaluate_eligibility(tmp_path)
        assert result.status == "ELIGIBLE"

    def test_blocked_when_missing(self, tmp_path: Path) -> None:
        result = evaluate_eligibility(tmp_path)
        assert result.status == "BLOCKED"
        assert result.reason == "install_state_missing"

    def test_blocked_when_installation_incomplete(self, tmp_path: Path) -> None:
        _write_raw_install_state(
            tmp_path,
            {
                "schema_version": 1, "phase": "s7.1", "installation_complete": False,
                "firstboot_provisioning": "pending", "source_media_version": "x",
                "source_commit": SOURCE_COMMIT,
            },
        )
        result = evaluate_eligibility(tmp_path)
        assert result.status == "BLOCKED"
        assert result.reason == "installation_not_complete"

    def test_not_required_when_already_complete(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path, firstboot_provisioning="complete")
        result = evaluate_eligibility(tmp_path)
        assert result.status == "NOT_REQUIRED"

    def test_blocked_on_live_media_even_with_valid_handoff(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        proc = tmp_path / "proc"
        proc.mkdir()
        (proc / "cmdline").write_text("boot=casper")
        result = evaluate_eligibility(tmp_path)
        assert result.status == "BLOCKED"
        assert "live_media_detected" in result.reason


# --------------------------------------------------------------------------
# Atomic writes (Section 27)
# --------------------------------------------------------------------------


class TestAtomicWrites:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "state.json"
        atomic_write_json(path, {"a": 1})
        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}

    def test_interrupted_write_leaves_original_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "state.json"
        atomic_write_json(path, {"a": 1})
        original = path.read_text(encoding="utf-8")

        import serein.firstboot.atomic as atomic_mod

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated interrupted rename")

        monkeypatch.setattr(atomic_mod.os, "replace", _boom)

        with pytest.raises(OSError):
            atomic_write_json(path, {"a": 2})

        assert path.read_text(encoding="utf-8") == original
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".state.json.")]
        assert leftovers == []


# --------------------------------------------------------------------------
# Locking (Section 28)
# --------------------------------------------------------------------------


class TestLocking:
    def test_second_concurrent_acquire_fails(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "fb.lock"
        first = FirstbootLock(lock_path)
        second = FirstbootLock(lock_path)
        assert first.acquire() is True
        try:
            assert second.acquire() is False
            assert is_lock_held(lock_path) is True
        finally:
            first.release()
        assert second.acquire() is True
        second.release()

    def test_context_manager_releases_on_exit(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "fb.lock"
        with FirstbootLock(lock_path):
            assert is_lock_held(lock_path) is True
        assert is_lock_held(lock_path) is False

    def test_is_lock_held_false_when_never_acquired(self, tmp_path: Path) -> None:
        assert is_lock_held(tmp_path / "never-created.lock") is False


# --------------------------------------------------------------------------
# State file (Section 6-9, 27)
# --------------------------------------------------------------------------


class TestStateFile:
    def test_load_default_is_pending_with_all_steps(self, tmp_path: Path) -> None:
        store = FirstbootStateStore(tmp_path / "state.json")
        state = store.load()
        assert state.state == "pending"
        assert [s.id for s in state.steps] == list(STEP_IDS)
        assert store.exists() is False  # load() never creates the file

    def test_save_and_reload_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        store = FirstbootStateStore(path)
        state = store.load()
        state.state = "running"
        store.save(state)
        reloaded = FirstbootStateStore(path).load()
        assert reloaded.state == "running"

    def test_corrupt_state_is_reported_not_raised(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("{not json", encoding="utf-8")
        state, error = FirstbootStateStore(path).load_corrupt_safe()
        assert state is None
        assert error is not None

    def test_reconciles_legacy_step_list(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        atomic_write_json(
            path,
            {
                "schema_version": 1, "state": "running", "started_at": None,
                "completed_at": None, "updated_at": None,
                "steps": [
                    {
                        "id": "01-validate-installation", "status": "passed",
                        "started_at": "t1", "completed_at": "t2", "failure_reason": None,
                    },
                    {
                        "id": "99-removed-legacy-step", "status": "passed",
                        "started_at": "t1", "completed_at": "t2", "failure_reason": None,
                    },
                ],
                "first_failure_stage": None, "first_failure_reason": None, "source_commit": None,
            },
        )
        state = FirstbootStateStore(path).load()
        assert [s.id for s in state.steps] == list(STEP_IDS)
        by_id = {s.id: s for s in state.steps}
        assert by_id["01-validate-installation"].status == "passed"
        assert by_id["02-initialize-directories"].status == "pending"


# --------------------------------------------------------------------------
# First-failure-wins (Section 9)
# --------------------------------------------------------------------------


class TestFirstFailureWins:
    def test_second_failure_never_overwrites_first(self) -> None:
        state = FirstbootState()
        _record_first_failure(state, "05-development-registration", "first reason")
        _record_first_failure(state, "07-cyber-registration", "later reason - must not win")
        assert state.first_failure_stage == "05-development-registration"
        assert state.first_failure_reason == "first reason"


# --------------------------------------------------------------------------
# The transactional engine (Section 6-9, 27-29, 33-37)
# --------------------------------------------------------------------------


class TestEngine:
    def test_full_success_flips_install_state_and_writes_evidence(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())

        assert result.status == "COMPLETE"
        assert result.mutated is True
        assert result.state is not None
        assert result.state.state == "complete"
        assert result.state.first_failure_stage is None
        assert all(s.status == "passed" for s in result.state.steps)

        install_state = json.loads(_install_state_path(tmp_path).read_text(encoding="utf-8"))
        assert install_state["firstboot_provisioning"] == "complete"
        assert install_state["source_commit"] == SOURCE_COMMIT
        assert install_state["schema_version"] == 1
        assert install_state["phase"] == "s7.1"

        evidence_path = tmp_path / FIRSTBOOT_EVIDENCE_RELATIVE_PATH
        assert evidence_path.exists()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert evidence["final_status"] == "complete"
        assert evidence["focus_default"]["policy_baseline"] == "balanced"
        assert evidence["focus_default"]["applied"] is False
        assert evidence["network_required"] is False

    def test_second_run_is_idempotent_no_op(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        runner = FakeCommandRunner()
        first = run_firstboot(root=tmp_path, runner=runner)
        assert first.status == "COMPLETE"

        state_path = tmp_path / FIRSTBOOT_STATE_RELATIVE_PATH
        before = state_path.read_text(encoding="utf-8")

        second = run_firstboot(root=tmp_path, runner=runner)
        assert second.status == "NOT_REQUIRED"
        assert second.mutated is False
        assert state_path.read_text(encoding="utf-8") == before

    def test_missing_handoff_blocks_with_zero_mutation(self, tmp_path: Path) -> None:
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "BLOCKED"
        assert result.mutated is False
        assert not (tmp_path / "var").exists()

    def test_malformed_handoff_blocks_with_zero_mutation(self, tmp_path: Path) -> None:
        path = _install_state_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "BLOCKED"
        assert result.mutated is False
        assert not (tmp_path / "var").exists()

    def test_installation_incomplete_blocks_with_zero_mutation(self, tmp_path: Path) -> None:
        _write_raw_install_state(
            tmp_path,
            {
                "schema_version": 1, "phase": "s7.1", "installation_complete": False,
                "firstboot_provisioning": "pending", "source_media_version": "x",
                "source_commit": SOURCE_COMMIT,
            },
        )
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "BLOCKED"
        assert result.mutated is False
        assert not (tmp_path / "var").exists()

    def test_already_complete_is_noop_zero_mutation(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path, firstboot_provisioning="complete")
        before = _install_state_path(tmp_path).read_text(encoding="utf-8")
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "NOT_REQUIRED"
        assert result.mutated is False
        assert not (tmp_path / "var").exists()
        assert _install_state_path(tmp_path).read_text(encoding="utf-8") == before

    def test_live_media_blocks_with_zero_mutation(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        proc = tmp_path / "proc"
        proc.mkdir()
        (proc / "cmdline").write_text("boot=casper")
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "BLOCKED"
        assert result.mutated is False
        assert not (tmp_path / "var").exists()

    def test_concurrent_run_reports_locked_with_exactly_one_mutation_owner(
        self, tmp_path: Path
    ) -> None:
        _write_valid_install_state(tmp_path)
        lock_path = tmp_path / FIRSTBOOT_LOCK_RELATIVE_PATH
        holder = FirstbootLock(lock_path)
        assert holder.acquire() is True
        try:
            blocked = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
            assert blocked.status == "LOCKED"
            assert blocked.mutated is False
            assert not (tmp_path / FIRSTBOOT_STATE_RELATIVE_PATH).exists()
        finally:
            holder.release()

        proceeds = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert proceeds.status == "COMPLETE"

    def test_crash_retry_does_not_duplicate_passed_steps_and_completes(
        self, tmp_path: Path
    ) -> None:
        """Section 29's required proof: step1 PASS, step2 PASS, step3
        FAIL, reboot; on retry step1/2 are not re-run, step3 is retried
        safely, and remaining steps continue."""
        _write_valid_install_state(tmp_path)
        runner = FakeCommandRunner()

        def _inject_failure(_ctx: object) -> StepOutcome:
            return StepOutcome(
                passed=False, detail="injected failure for test", reason="injected_failure"
            )

        steps_with_injection = tuple(
            StepDefinition(s.id, s.title, _inject_failure)
            if s.id == "03-apply-core-config"
            else s
            for s in DEFAULT_STEPS
        )

        first = run_firstboot(root=tmp_path, runner=runner, steps=steps_with_injection)
        assert first.status == "FAILED"
        assert first.state is not None
        assert first.state.first_failure_stage == "03-apply-core-config"
        assert first.state.first_failure_reason == "injected_failure"

        statuses = {s.id: s.status for s in first.state.steps}
        assert statuses["01-validate-installation"] == "passed"
        assert statuses["02-initialize-directories"] == "passed"
        assert statuses["03-apply-core-config"] == "failed"
        for later_id in STEP_IDS[3:]:
            assert statuses[later_id] == "pending"

        by_id = {s.id: s for s in first.state.steps}
        step1_started_at = by_id["01-validate-installation"].started_at
        step2_started_at = by_id["02-initialize-directories"].started_at

        # "Reboot" - retry with the real step sequence (bug fixed).
        second = run_firstboot(root=tmp_path, runner=runner, steps=DEFAULT_STEPS)
        assert second.status == "COMPLETE"
        assert second.state is not None
        assert second.state.first_failure_stage is None
        assert second.state.first_failure_reason is None

        by_id_2 = {s.id: s for s in second.state.steps}
        assert by_id_2["01-validate-installation"].started_at == step1_started_at
        assert by_id_2["02-initialize-directories"].started_at == step2_started_at
        assert all(s.status == "passed" for s in second.state.steps)

    def test_step_raising_is_caught_and_recorded_as_failure(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)

        def _raises(_ctx: object) -> StepOutcome:
            raise RuntimeError("boom")

        steps = tuple(
            StepDefinition(s.id, s.title, _raises) if s.id == "02-initialize-directories" else s
            for s in DEFAULT_STEPS
        )
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner(), steps=steps)
        assert result.status == "FAILED"
        assert result.state is not None
        assert result.state.first_failure_stage == "02-initialize-directories"
        assert "boom" in (result.state.first_failure_reason or "")


# --------------------------------------------------------------------------
# Read-only status/doctor/plan (Section 12, 13, 32)
# --------------------------------------------------------------------------


class TestReadOnlyCommands:
    def test_status_not_started(self, tmp_path: Path) -> None:
        status = build_firstboot_status(root=tmp_path)
        assert status.eligibility_status == "BLOCKED"
        assert status.state == "not_started"

    def test_status_reflects_complete_run(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        status = build_firstboot_status(root=tmp_path)
        assert status.state == "complete"
        assert status.steps_summary["passed"] == len(STEP_IDS)

    def test_plan_is_side_effect_free(self, tmp_path: Path) -> None:
        plan = build_firstboot_plan(root=tmp_path)
        assert plan.mutation == "none"
        assert len(plan.steps) == len(STEP_IDS)
        assert not (tmp_path / "var").exists()
        assert not (tmp_path / "etc").exists()

    def test_doctor_missing_handoff_is_skip_not_fail(self, tmp_path: Path) -> None:
        report = run_firstboot_checks(root=tmp_path, runner=FakeCommandRunner())
        check = next(c for c in report.checks if c.id == "firstboot_handoff_present")
        assert check.status.value == "SKIP"
        assert report.exit_code == 0

    def test_doctor_malformed_handoff_is_fail(self, tmp_path: Path) -> None:
        path = _install_state_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{bad", encoding="utf-8")
        report = run_firstboot_checks(root=tmp_path, runner=FakeCommandRunner())
        check = next(c for c in report.checks if c.id == "firstboot_handoff_valid")
        assert check.status.value == "FAIL"
        assert report.exit_code == 1

    def test_doctor_lock_held_is_warn(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        lock_path = tmp_path / FIRSTBOOT_LOCK_RELATIVE_PATH
        lock = FirstbootLock(lock_path)
        assert lock.acquire() is True
        try:
            report = run_firstboot_checks(root=tmp_path, runner=FakeCommandRunner())
            check = next(c for c in report.checks if c.id == "firstboot_lock_available")
            assert check.status.value == "WARN"
        finally:
            lock.release()

    def test_doctor_already_complete_is_pass(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        report = run_firstboot_checks(root=tmp_path, runner=FakeCommandRunner())
        check = next(c for c in report.checks if c.id == "firstboot_state_readable")
        assert check.status.value == "PASS"
        assert report.exit_code == 0


# --------------------------------------------------------------------------
# Safety invariants (Section 18-21)
# --------------------------------------------------------------------------


class TestOSIdentity:
    def test_step_02_writes_and_verifies_serein_identity(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "COMPLETE"
        for name in ("os-release", "issue", "issue.net"):
            assert (tmp_path / "etc" / name).is_file()
        os_release = (tmp_path / "etc" / "os-release").read_text(encoding="utf-8")
        assert "ID=serein" in os_release
        assert "ID_LIKE=ubuntu" in os_release


class TestSafetyInvariants:
    def test_focus_default_is_balanced_and_never_applied(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.evidence is not None
        focus_default = result.evidence.focus_default
        assert focus_default is not None
        assert focus_default["policy_baseline"] == "balanced"
        assert focus_default["runtime_enforcement"] is False
        assert focus_default["applied"] is False

    def test_no_network_dependency_for_core_completion(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        # FakeCommandRunner never touches a real network - a COMPLETE
        # result here already proves core provisioning does not require
        # network access.
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "COMPLETE"
        assert result.evidence is not None
        assert result.evidence.network_required is False

    def test_desktop_baseline_verifies_staged_resources_and_records_version(
        self, tmp_path: Path
    ) -> None:
        # _write_valid_install_state stages the system-owned resources
        # first (mimicking a real package/install-time staging step) -
        # step_desktop_baseline's own job is narrower: verify they
        # landed, then record the config-version marker.
        _write_valid_install_state(tmp_path)
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "COMPLETE"
        assert result.evidence is not None
        record = result.evidence.desktop_baseline
        assert record is not None
        assert record["config_version"] == 1
        version_marker = tmp_path / "etc" / "serein" / "desktop" / "config-version"
        assert version_marker.is_file()

    def test_desktop_baseline_fails_closed_when_resources_not_staged(
        self, tmp_path: Path
    ) -> None:
        # A bare install-state marker with NO desktop resources staged
        # (staging is a package/install-time concern - not yet
        # implemented, SEREIN-DESKTOP-STAGING-PENDING) - the step must
        # fail closed rather than falsely record a config-version.
        marker = build_install_state_marker(
            source_commit=SOURCE_COMMIT, source_media_version="26.04.1"
        )
        atomic_write_json(_install_state_path(tmp_path), marker.to_dict())
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.status == "FAILED"
        assert result.state is not None
        assert result.state.first_failure_stage == "04-desktop-baseline"
        version_marker = tmp_path / "etc" / "serein" / "desktop" / "config-version"
        assert not version_marker.is_file()


# --------------------------------------------------------------------------
# Schema contracts
# --------------------------------------------------------------------------


class TestSchemas:
    @pytest.mark.parametrize(
        "name", ["firstboot-state.schema.json", "firstboot-evidence.schema.json"]
    )
    def test_schema_file_is_valid_json_schema(self, name: str) -> None:
        schema = _load_schema(name)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_state_validates_against_schema(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        state = FirstbootStateStore(tmp_path / FIRSTBOOT_STATE_RELATIVE_PATH).load()
        schema = _load_schema("firstboot-state.schema.json")
        jsonschema.validate(instance=state.to_dict(), schema=schema)

    def test_evidence_validates_against_schema(self, tmp_path: Path) -> None:
        _write_valid_install_state(tmp_path)
        result = run_firstboot(root=tmp_path, runner=FakeCommandRunner())
        assert result.evidence is not None
        schema = _load_schema("firstboot-evidence.schema.json")
        jsonschema.validate(instance=result.evidence.to_dict(), schema=schema)
