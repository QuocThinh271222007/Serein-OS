"""The transactional first-boot provisioning engine (Section 6-9,
27-29).

``run_firstboot`` is the ONLY function in this repository that may
actually mutate an installed system on S7.2's behalf - every other
module in ``serein.firstboot`` (``status``, ``doctor``, ``plan``) is
read-only. It implements:

- eligibility gating (Section 5, 10, 33-37) - checked *before* any lock
  is taken or any file is written, so a blocked/not-required run causes
  zero mutation;
- single-owner concurrency via :class:`serein.firstboot.lock.FirstbootLock`
  (Section 28);
- step-by-step checkpointing - state is persisted atomically after every
  single step transition, never only at the end (Section 6, 27);
- stop-on-first-failure with first-failure-wins evidence (Section 9,
  mirroring ``distribution/scripts/record-failure.sh``);
- idempotent retry - an already-``passed`` step is never re-run
  (Section 6, 29).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT

from .eligibility import evaluate_eligibility
from .evidence import assemble_firstboot_evidence, write_firstboot_evidence
from .lock import FirstbootLock
from .models import (
    FIRSTBOOT_EVIDENCE_RELATIVE_PATH,
    FIRSTBOOT_LOCK_RELATIVE_PATH,
    FIRSTBOOT_STATE_RELATIVE_PATH,
    EligibilityResult,
    FirstbootEvidence,
    FirstbootState,
    StepRecord,
)
from .statefile import FirstbootStateStore
from .steps import DEFAULT_STEPS, StepDefinition, build_context

_RUN_STATUSES = ("COMPLETE", "FAILED", "BLOCKED", "NOT_REQUIRED", "LOCKED")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


@dataclass(frozen=True)
class FirstbootRunResult:
    status: str  # one of _RUN_STATUSES
    mutated: bool
    eligibility: EligibilityResult
    state: FirstbootState | None
    evidence: FirstbootEvidence | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status not in _RUN_STATUSES:
            raise ValueError(f"status={self.status!r} must be one of {_RUN_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mutated": self.mutated,
            "eligibility": self.eligibility.to_dict(),
            "state": self.state.to_dict() if self.state is not None else None,
            "evidence": self.evidence.to_dict() if self.evidence is not None else None,
            "reason": self.reason,
        }


def _record_first_failure(state: FirstbootState, stage: str, reason: str | None) -> None:
    """Mirrors ``distribution/scripts/record-failure.sh``'s "first stage
    failure wins, never overwritten" discipline (Section 9), reimplemented
    for this in-process Python state machine."""
    if state.first_failure_stage is None:
        state.first_failure_stage = stage
        state.first_failure_reason = reason
    # else: an earlier stage's failure is already recorded - this later
    # failure is not recorded as the blocker, exactly like the shell
    # helper's stderr note for a second `record-failure.sh` call.


def run_firstboot(
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
    steps: Sequence[StepDefinition] = DEFAULT_STEPS,
    now: Any = _utcnow,
) -> FirstbootRunResult:
    eligibility = evaluate_eligibility(root)

    if eligibility.status == "NOT_REQUIRED":
        return FirstbootRunResult(
            status="NOT_REQUIRED", mutated=False, eligibility=eligibility,
            state=None, evidence=None, reason=eligibility.reason,
        )
    if eligibility.status == "BLOCKED":
        return FirstbootRunResult(
            status="BLOCKED", mutated=False, eligibility=eligibility,
            state=None, evidence=None, reason=eligibility.reason,
        )

    lock_path = root / FIRSTBOOT_LOCK_RELATIVE_PATH
    lock = FirstbootLock(lock_path)
    if not lock.acquire():
        return FirstbootRunResult(
            status="LOCKED", mutated=False, eligibility=eligibility,
            state=None, evidence=None,
            reason="another first-boot provisioning run currently holds the lock",
        )

    try:
        return _run_locked(root, runner, steps, now, eligibility)
    finally:
        lock.release()


def _run_locked(
    root: Path,
    runner: CommandRunner,
    steps: Sequence[StepDefinition],
    now: Any,
    eligibility: EligibilityResult,
) -> FirstbootRunResult:
    store = FirstbootStateStore(root / FIRSTBOOT_STATE_RELATIVE_PATH)
    state = store.load()

    if state.state == "complete":
        return FirstbootRunResult(
            status="NOT_REQUIRED", mutated=False, eligibility=eligibility,
            state=state, evidence=None, reason="firstboot state already complete",
        )

    marker = eligibility.install_state.marker
    assert marker is not None  # ELIGIBLE/handled states guarantee this

    ctx = build_context(root, marker, runner)
    # Section 29: seed the context's step-status view from whatever this
    # (possibly resumed) run already knows was persisted - so a step like
    # 10-final-validation correctly sees an earlier invocation's already-
    # "passed" steps even though they are skipped (not re-run) this time.
    ctx.step_statuses.update({s.id: s.status for s in state.steps})
    mutated = False

    if state.state == "pending":
        state.state = "running"
        state.started_at = _iso(now())
        state.source_commit = marker.source_commit
    elif state.state == "failed":
        state.state = "running"
    # "running" (resumed after a crash mid-run) is kept as-is.

    store.save(state, now_iso=_iso(now()))
    mutated = True

    stopped_due_to_failure = False
    step_by_id = {s.id: s for s in state.steps}

    for step_def in steps:
        record = step_by_id[step_def.id]
        if record.status == "passed":
            continue  # Section 6/29: never re-run an already-successful step.

        record = StepRecord(id=step_def.id, status="running", started_at=_iso(now()))
        _set_step(state, record)
        store.save(state, now_iso=_iso(now()))

        try:
            outcome = step_def.func(ctx)
        except Exception as exc:  # noqa: BLE001 - a step must never crash the engine
            from .steps import StepOutcome

            outcome = StepOutcome(passed=False, detail=f"step raised: {exc}", reason=str(exc))

        ctx.evidence[step_def.id] = dict(outcome.evidence)

        if outcome.passed:
            record = StepRecord(
                id=step_def.id, status="passed",
                started_at=record.started_at, completed_at=_iso(now()),
            )
            _set_step(state, record)
            ctx.step_statuses[step_def.id] = "passed"
            if state.first_failure_stage == step_def.id:
                # Section 29: this stage was retried and now passes - the
                # previously-recorded failure evidence is stale (it no
                # longer describes reality) and is cleared.
                state.first_failure_stage = None
                state.first_failure_reason = None
            store.save(state, now_iso=_iso(now()))
        else:
            reason = outcome.reason or outcome.detail
            record = StepRecord(
                id=step_def.id, status="failed",
                started_at=record.started_at, completed_at=_iso(now()),
                failure_reason=reason,
            )
            _set_step(state, record)
            ctx.step_statuses[step_def.id] = "failed"
            _record_first_failure(state, step_def.id, reason)
            state.state = "failed"
            store.save(state, now_iso=_iso(now()))
            stopped_due_to_failure = True
            break

    if not stopped_due_to_failure:
        state.state = "complete"
        state.completed_at = _iso(now())
        store.save(state, now_iso=_iso(now()))

    evidence = assemble_firstboot_evidence(marker, state, ctx.evidence, eligibility)
    write_firstboot_evidence(evidence, root / FIRSTBOOT_EVIDENCE_RELATIVE_PATH)

    status = "COMPLETE" if state.state == "complete" else "FAILED"
    return FirstbootRunResult(
        status=status, mutated=mutated, eligibility=eligibility,
        state=state, evidence=evidence,
        reason=None if status == "COMPLETE" else state.first_failure_reason,
    )


def _set_step(state: FirstbootState, record: StepRecord) -> None:
    for index, existing in enumerate(state.steps):
        if existing.id == record.id:
            state.steps[index] = record
            return
    state.steps.append(record)
