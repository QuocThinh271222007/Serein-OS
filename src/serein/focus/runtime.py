"""S6.5 Focus runtime boundary (Phase-7-completion Section 26-29).

ADR-0026 established Focus as *planning-only* deliberately, pending a
future runtime executor - this module is that executor. It never
re-derives policy: every weight/readiness/conflict decision still
comes from ``serein.focus.policy``/``serein.focus.transition``
unchanged (Section 2 - "reuse before rewrite"). This module's own job
is narrower - turn an already-*planned* transition into a real
systemd cgroup-v2 slice hierarchy, following the transaction contract
Section 27 specifies:

    REQUEST -> RESOLVE CURRENT STATE -> PLAN -> VALIDATE -> PREPARE ->
    APPLY -> VERIFY -> COMMIT ACTIVE FOCUS
    (failure at APPLY/VERIFY -> ROLLBACK, previous committed focus
    retained, active-focus state is never updated before VERIFY
    succeeds)

Slice hierarchy - exactly ``docs/focus/future-runtime.md``'s own
pre-documented sketch, unchanged:

    serein.slice
    +-- serein-dev.slice
    +-- serein-ai.slice
    +-- serein-cyber.slice
    +-- serein-background.slice   (fixed, policy-independent - see below)

``private`` is deliberately NOT a slice here, matching that same
document's own reasoning: privacy correctness needs a stronger
boundary than a cgroup weight can provide (a VM/isolation boundary -
Whonix, or a future Veil workspace boundary - not simply "lower CPU
priority"). This executor never attempts to enforce ``private``
focus's resource preference via a slice; ``to_focus="private"``
still runs the full transaction (plan/validate/commit), it just
writes no domain-specific slice for it.

Every ``CPUWeight=``/``IOWeight=`` value is the exact same
``RELATIVE_WEIGHTS`` table ``FocusPolicy.resource_intents`` already
uses (Section 19-20's own "relative preference during contention,
never a percentage/throughput guarantee" framing) - this module never
invents a second weight table. ``serein-background.slice`` gets no
explicit weight (systemd's own unset default) - it represents
everything NOT currently a recognized focus domain, and Section 26
never asked for a fifth weight tier to invent a number for.

GPU: ``FocusPolicy.gpu_intent.enforceable`` is already always
``False`` in the existing model (no cross-vendor cgroup GPU-ownership
mechanism exists on Linux - Section 29) - this module never attempts
to touch GPU state and always reports it ``NOT_ENFORCEABLE`` rather
than silently omitting it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.firstboot.atomic import atomic_write_json
from serein.focus.evidence import gather_focus_evidence
from serein.focus.models import FOCUS_DOMAINS, FOCUS_TARGETS, RELATIVE_WEIGHTS, FocusPolicy
from serein.focus.policy import build_focus_policy
from serein.focus.transition import build_focus_transition
from serein.hardware._util import DEFAULT_ROOT

FOCUS_RUNTIME_STATE_SCHEMA_VERSION = 1
FOCUS_RUNTIME_RESULT_SCHEMA_VERSION = 1

#: Section 28: the ONE authoritative persisted active-focus record -
#: every consumer (Fastfetch, KRunner, CLI, desktop) reads this SAME
#: file, never a private copy. Distinct from
#: ``serein.firstboot.models.FOCUS_DEFAULT_RELATIVE_PATH`` (the
#: pre-first-transition baseline *label* first-boot writes - never
#: itself a runtime commit).
FOCUS_RUNTIME_STATE_RELATIVE_PATH = "var/lib/serein/focus/state.json"

#: docs/focus/future-runtime.md's own pre-documented sketch - "private"
#: is deliberately excluded (see module docstring).
_DOMAIN_SLICE_NAMES: dict[str, str] = {
    "dev": "serein-dev.slice",
    "ai": "serein-ai.slice",
    "cyber": "serein-cyber.slice",
}
_PARENT_SLICE_NAME = "serein.slice"
_BACKGROUND_SLICE_NAME = "serein-background.slice"
_ALL_SLICE_NAMES: tuple[str, ...] = (
    _PARENT_SLICE_NAME,
    *_DOMAIN_SLICE_NAMES.values(),
    _BACKGROUND_SLICE_NAME,
)

#: Section 8/72: systemd system slice-unit directory - a plain,
#: system-owned config path, never a user unit.
_SLICE_UNIT_DIR_RELATIVE = "etc/systemd/system"

RUNTIME_STATUSES: tuple[str, ...] = ("committed", "rolled_back", "blocked", "failed")


@dataclass(frozen=True)
class SliceApplyResult:
    slice_name: str
    cpu_weight: int | None
    io_weight: int | None
    written: bool
    verified: bool | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_name": self.slice_name,
            "cpu_weight": self.cpu_weight,
            "io_weight": self.io_weight,
            "written": self.written,
            "verified": self.verified,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FocusRuntimeResult:
    schema_version: int
    status: str  # one of RUNTIME_STATUSES
    from_focus: str
    to_focus: str
    slice_results: tuple[SliceApplyResult, ...]
    gpu_note: str
    attempted_at: str
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "from_focus": self.from_focus,
            "to_focus": self.to_focus,
            "slice_results": [s.to_dict() for s in self.slice_results],
            "gpu_note": self.gpu_note,
            "attempted_at": self.attempted_at,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FocusRuntimeState:
    """The persisted record (Section 28). ``active_focus`` stays
    ``"balanced"`` (never fabricated as something a real transition
    committed) until :func:`apply_focus_transition` actually commits
    one."""

    schema_version: int
    active_focus: str
    committed_at: str | None
    last_result: FocusRuntimeResult | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "active_focus": self.active_focus,
            "committed_at": self.committed_at,
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }


def _state_path(root: Path) -> Path:
    return root / FOCUS_RUNTIME_STATE_RELATIVE_PATH


def read_focus_runtime_state(root: Path = DEFAULT_ROOT) -> FocusRuntimeState:
    """Section 28: "at boot, validate persisted state; fallback safely
    if invalid." Never raises - a missing, corrupt, or unrecognized
    ``active_focus`` all safely resolve to the ``"balanced"`` default,
    exactly the same fallback ``DEFAULT_FOCUS_BASELINE`` already uses
    elsewhere."""
    path = _state_path(root)
    if not path.is_file():
        return FocusRuntimeState(FOCUS_RUNTIME_STATE_SCHEMA_VERSION, "balanced", None, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        active = data.get("active_focus")
        if active not in FOCUS_TARGETS:
            raise ValueError(f"unrecognized active_focus: {active!r}")
        return FocusRuntimeState(
            schema_version=FOCUS_RUNTIME_STATE_SCHEMA_VERSION,
            active_focus=active,
            committed_at=data.get("committed_at"),
            last_result=None,  # not re-parsed on read - see module note below
        )
    except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
        return FocusRuntimeState(FOCUS_RUNTIME_STATE_SCHEMA_VERSION, "balanced", None, None)


def _slice_unit_text(name: str, cpu_weight: int | None, io_weight: int | None) -> str:
    lines = ["[Unit]", f"Description=Serein Focus slice: {name}"]
    if name != _PARENT_SLICE_NAME:
        lines.append(f"After={_PARENT_SLICE_NAME}")
    lines += ["", "[Slice]"]
    if cpu_weight is not None:
        lines.append(f"CPUWeight={cpu_weight}")
    if io_weight is not None:
        lines.append(f"IOWeight={io_weight}")
    return "\n".join(lines) + "\n"


def _weight_for(policy: FocusPolicy, domain: str) -> int:
    role = next(r for r in policy.domain_roles if r.domain == domain)
    return RELATIVE_WEIGHTS[role.state]


def _prepare_slice_plan(policy: FocusPolicy) -> dict[str, tuple[int | None, int | None]]:
    """PREPARE (Section 27): compute the target CPUWeight/IOWeight for
    every slice from ``policy`` - never from ad hoc logic here. The
    parent ``serein.slice`` and ``serein-background.slice`` carry no
    explicit weight (systemd's own unset default)."""
    plan: dict[str, tuple[int | None, int | None]] = {
        _PARENT_SLICE_NAME: (None, None),
        _BACKGROUND_SLICE_NAME: (None, None),
    }
    for domain, slice_name in _DOMAIN_SLICE_NAMES.items():
        weight = _weight_for(policy, domain)
        plan[slice_name] = (weight, weight)
    return plan


def _apply_slices(
    plan: dict[str, tuple[int | None, int | None]], root: Path
) -> list[SliceApplyResult]:
    unit_dir = root / _SLICE_UNIT_DIR_RELATIVE
    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [
            SliceApplyResult(name, *plan[name], False, False, f"could not create {unit_dir}: {exc}")
            for name in _ALL_SLICE_NAMES
        ]

    results: list[SliceApplyResult] = []
    for name in _ALL_SLICE_NAMES:
        cpu_weight, io_weight = plan[name]
        target = unit_dir / name
        text = _slice_unit_text(name, cpu_weight, io_weight)
        try:
            target.write_text(text, encoding="utf-8")
            written = True
        except OSError as exc:
            results.append(SliceApplyResult(name, cpu_weight, io_weight, False, False, str(exc)))
            continue
        verified = target.is_file() and target.read_text(encoding="utf-8") == text
        reason = (
            "wrote and re-read the unit file" if verified
            else "write succeeded but readback mismatched"
        )
        results.append(SliceApplyResult(name, cpu_weight, io_weight, written, verified, reason))
    return results


def apply_focus_transition(
    to_focus: str,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
    home: Path | None = None,
) -> FocusRuntimeResult:
    """The real transaction executor (Section 27). Never updates the
    persisted active-focus state before every slice write has been
    verified - a failure at APPLY/VERIFY rolls back (the previous
    committed focus is retained; the unit files already written for
    this attempt are simply never referenced by the persisted state,
    since commit only happens after every one verifies)."""
    now = datetime.now(UTC).isoformat()

    if to_focus not in FOCUS_TARGETS:
        return FocusRuntimeResult(
            FOCUS_RUNTIME_RESULT_SCHEMA_VERSION, "failed", "unknown", to_focus, (),
            "NOT_ENFORCEABLE - no cross-vendor cgroup GPU-ownership mechanism exists "
            "(Section 29); Focus never attempts to enforce GPU placement.",
            now, f"unknown focus target: {to_focus!r}",
        )

    current_state = read_focus_runtime_state(root)
    from_focus = current_state.active_focus

    evidence = gather_focus_evidence(root=root, runner=runner, home=home)
    transition_plan = build_focus_transition(from_focus, to_focus, evidence)

    gpu_note = (
        "NOT_ENFORCEABLE - no cross-vendor cgroup GPU-ownership mechanism exists "
        "(Section 29); Focus never attempts to enforce GPU placement."
    )

    if transition_plan.status == "BLOCKED":
        return FocusRuntimeResult(
            FOCUS_RUNTIME_RESULT_SCHEMA_VERSION, "blocked", from_focus, to_focus, (),
            gpu_note, now,
            f"transition plan blocked: {'; '.join(transition_plan.blockers) or 'unspecified'}",
        )

    if transition_plan.status == "NOOP":
        # Section 27: from_focus == to_focus - nothing to apply, but
        # this IS a real, honest COMMIT (re-affirming the same focus),
        # never an error.
        result = FocusRuntimeResult(
            FOCUS_RUNTIME_RESULT_SCHEMA_VERSION, "committed", from_focus, to_focus, (),
            gpu_note, now, "NOOP transition (already active)",
        )
        _persist(root, to_focus, now, result)
        return result

    target_policy = build_focus_policy(to_focus, evidence)
    slice_plan = _prepare_slice_plan(target_policy)
    slice_results = _apply_slices(slice_plan, root)

    all_verified = all(r.verified for r in slice_results)
    if not all_verified:
        # ROLLBACK: never persist - the previous committed focus
        # remains authoritative regardless of what got written to disk.
        return FocusRuntimeResult(
            FOCUS_RUNTIME_RESULT_SCHEMA_VERSION, "rolled_back", from_focus, to_focus,
            tuple(slice_results), gpu_note, now,
            "one or more slice units failed to write/verify - previous focus retained",
        )

    result = FocusRuntimeResult(
        FOCUS_RUNTIME_RESULT_SCHEMA_VERSION, "committed", from_focus, to_focus,
        tuple(slice_results), gpu_note, now, None,
    )
    _persist(root, to_focus, now, result)
    return result


def _persist(
    root: Path, active_focus: str, committed_at: str, result: FocusRuntimeResult
) -> None:
    state = FocusRuntimeState(
        FOCUS_RUNTIME_STATE_SCHEMA_VERSION, active_focus, committed_at, result
    )
    atomic_write_json(_state_path(root), state.to_dict())


__all__ = [
    "FOCUS_DOMAINS",
    "FOCUS_RUNTIME_STATE_RELATIVE_PATH",
    "FocusRuntimeResult",
    "FocusRuntimeState",
    "SliceApplyResult",
    "apply_focus_transition",
    "read_focus_runtime_state",
]
