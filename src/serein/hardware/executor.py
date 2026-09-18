"""S2 hardware apply engine (Phase-7-completion Section 25).

Consumes ``HardwarePlan``/``PlanAction`` from ``serein.hardware.planner``
- never re-detects hardware independently, and never proposes an
action of its own; the planner remains the single source of truth for
*what* is safe to do, this module only ever performs *how*.

Executes only ``status="APPLY"`` actions whose ``action`` this executor
actually knows how to perform. Every other APPLY action (including one
a future planner change adds that this executor has not caught up to
yet) is honestly reported ``not_enforceable`` rather than silently
skipped or falsely claimed applied - mirroring the GPU-focus principle
(Section 29 of the Phase-7-completion brief): never pretend generic
code can enforce something it cannot actually verify.

Two actions are implemented in this round (Section 25's own named
examples): power-profile selection (``set_power_profile``, via
``powerprofilesctl set``/``get``) and ZRAM configuration
(``configure_zram``, a plain config-file write of this repository's
own pinned ``hardware/defaults/zram-generator.conf``, written to the
``.conf.d/`` override directory - never overwriting
``/etc/systemd/zram-generator.conf`` itself, which is upstream/package
territory - and verified via the SAME ``detect_memory_policy`` reader
the planner itself already trusts). CPU energy-performance-preference
and per-device IO-scheduler sysfs writes are understood, scoped, and
deliberately deferred to a later round - see
docs/hardware/known-limitations.md
(SEREIN-HARDWARE-EXECUTOR-CPU-IO-PENDING) - never silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.models import HardwarePlan, PlanAction

#: Actions this executor knows how to actually perform.
_IMPLEMENTED_ACTIONS = frozenset({"set_power_profile", "configure_zram"})

#: hardware/defaults/zram-generator.conf is this project's own pinned,
#: reviewed default (see that file's own header) - never invented ad
#: hoc here. Written to the override directory, never the base file.
_ZRAM_DEFAULT_SOURCE_RELATIVE = "hardware/defaults/zram-generator.conf"
_ZRAM_TARGET_RELATIVE = "etc/systemd/zram-generator.conf.d/90-serein.conf"

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    status: str  # "applied"|"noop"|"skip"|"blocked"|"not_enforceable"|"failed"
    detail: str
    changed: bool
    verified: bool | None  # None = verification not attempted
    reversible: bool
    rollback_available: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status,
            "detail": self.detail,
            "changed": self.changed,
            "verified": self.verified,
            "reversible": self.reversible,
            "rollback_available": self.rollback_available,
            "evidence": self.evidence,
        }


def _apply_power_profile(action: PlanAction, runner: CommandRunner) -> ActionResult:
    if action.target is None:
        return ActionResult(
            action.id, "failed", "plan action has no target profile", False, None,
            action.reversible, False,
        )
    result = runner.run(["powerprofilesctl", "set", action.target])
    if result is None or result.returncode != 0:
        return ActionResult(
            action.id, "failed",
            f"powerprofilesctl set {action.target!r} failed or is unavailable",
            False, False, action.reversible, False,
            evidence={
                "stderr": result.stderr if result is not None else "command not found",
            },
        )

    verify = runner.run(["powerprofilesctl", "get"])
    observed = verify.stdout.strip() if verify is not None and verify.stdout else None
    verified = observed == action.target
    return ActionResult(
        action.id, "applied" if verified else "failed",
        f"set power profile to {action.target!r} (observed: {observed!r})",
        True, verified, action.reversible,
        rollback_available=action.current is not None,
        evidence={"observed_profile": observed, "previous_profile": action.current},
    )


def _apply_zram(action: PlanAction, root: Path, repo_root: Path) -> ActionResult:
    source = repo_root / _ZRAM_DEFAULT_SOURCE_RELATIVE
    if not source.is_file():
        return ActionResult(
            action.id, "failed",
            f"pinned default {_ZRAM_DEFAULT_SOURCE_RELATIVE!r} is missing from this build",
            False, None, action.reversible, False,
        )

    target = root / _ZRAM_TARGET_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    memory_policy = detect_memory_policy(root)
    verified = bool(memory_policy.zram_generator_config_sources)
    return ActionResult(
        action.id, "applied" if verified else "failed",
        f"wrote {_ZRAM_TARGET_RELATIVE} from the pinned repository default",
        True, verified, action.reversible,
        rollback_available=False,  # no pre-existing file was overwritten (NOOP/SKIP already
        # cover every case where one exists - see planner._zram_action)
        evidence={"config_sources_after": memory_policy.zram_generator_config_sources},
    )


def apply_hardware_plan(
    plan: HardwarePlan,
    root: Path,
    runner: CommandRunner = DEFAULT_RUNNER,
    repo_root: Path = _REPO_ROOT,
) -> list[ActionResult]:
    """Validate -> apply -> verify -> record for every action in
    ``plan`` (Section 25). A NOOP/SKIP/BLOCKED action (the planner's
    own verdict - never re-decided here) is recorded as such, never
    attempted. An APPLY action this executor does not implement is
    recorded ``not_enforceable``, never silently skipped without a
    trace."""
    results: list[ActionResult] = []
    for action in plan.actions:
        if action.status != "APPLY":
            results.append(ActionResult(
                action.id, action.status.lower(), action.reason, False, None,
                action.reversible, False,
            ))
            continue
        if action.action not in _IMPLEMENTED_ACTIONS:
            results.append(ActionResult(
                action.id, "not_enforceable",
                f"executor has no implementation yet for action={action.action!r}",
                False, None, action.reversible, False,
            ))
            continue
        if action.action == "set_power_profile":
            results.append(_apply_power_profile(action, runner))
        elif action.action == "configure_zram":
            results.append(_apply_zram(action, root, repo_root))
    return results
