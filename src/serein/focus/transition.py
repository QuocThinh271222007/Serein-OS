"""``serein focus transition --from X --to Y``: deterministic transition
*simulation* only (Section 51-58). ``build_focus_transition()`` is the
one canonical function the CLI and doctor both consume (Section 89) -
it never executes anything; it computes two ``FocusPolicy`` snapshots
(via the same ``build_focus_policy()`` every other surface uses) and
reports the delta between them.

The transition state machine described in the S6.5 brief (REQUEST ->
OBSERVE -> PLAN -> CHECK CONSTRAINTS -> QUIESCE CANDIDATES -> RESOURCE
REWEIGHT -> ACTIVATE TARGET CANDIDATES -> VERIFY -> COMMIT FOCUS) stops
at PLAN here - every stage after it belongs to a future runtime
executor this phase does not implement (Section 52/113-114).
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.focus.evidence import FocusEvidence, gather_focus_evidence
from serein.focus.models import (
    FOCUS_DOMAINS,
    FOCUS_TARGETS,
    FOCUS_TRANSITION_SCHEMA_VERSION,
    FocusPolicy,
    FocusTransitionPlan,
    ResourceChange,
)
from serein.focus.policy import build_focus_policy
from serein.hardware._util import DEFAULT_ROOT

#: Domain-role-state -> qualitative memory-budget label (Section 25 -
#: never a precise byte target).
_MEMORY_LABEL: dict[str, str] = {
    "primary": "high", "secondary": "medium", "idle": "low", "off": "none",
}

#: Ordering used to pick the single "highest" cost among lifecycle
#: changes for the transition's own overall `cost` field.
_COST_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "unknown": 3}


def _domain_resource_changes(
    from_policy: FocusPolicy, to_policy: FocusPolicy
) -> list[ResourceChange]:
    changes: list[ResourceChange] = []
    from_roles = {role.domain: role for role in from_policy.domain_roles}
    to_roles = {role.domain: role for role in to_policy.domain_roles}
    for domain in FOCUS_DOMAINS:
        before_state = from_roles[domain].state
        after_state = to_roles[domain].state
        if before_state == after_state:
            continue
        changes.append(
            ResourceChange(
                "cpu", domain, before_state, after_state,
                f"{domain}'s role changes from {before_state} to {after_state} - "
                "a relative CPUWeight intent change only, never enforced.",
            )
        )
        changes.append(
            ResourceChange(
                "memory", domain, _MEMORY_LABEL[before_state], _MEMORY_LABEL[after_state],
                f"{domain}'s qualitative memory-budget target follows its role "
                "change - no precise byte target is ever claimed (Section 25).",
            )
        )
    return changes


def _gpu_resource_change(from_policy: FocusPolicy, to_policy: FocusPolicy) -> ResourceChange | None:
    before, after = from_policy.gpu_intent, to_policy.gpu_intent
    if before.mode == after.mode and before.preferred_domain == after.preferred_domain:
        return None
    before_label = before.preferred_domain or before.mode
    after_label = after.preferred_domain or after.mode
    domain = after.preferred_domain or before.preferred_domain or "shared"
    return ResourceChange(
        "gpu", domain, before_label, after_label,
        f"GPU lease intent moves from '{before.mode}' to '{after.mode}' - never "
        "enforced by any generic mechanism (Section 29-30).",
    )


def build_focus_transition(
    from_focus: str, to_focus: str, evidence: FocusEvidence
) -> FocusTransitionPlan:
    if from_focus not in FOCUS_TARGETS:
        raise ValueError(f"unknown focus target: {from_focus!r}")
    if to_focus not in FOCUS_TARGETS:
        raise ValueError(f"unknown focus target: {to_focus!r}")

    from_policy = build_focus_policy(from_focus, evidence)

    if from_focus == to_focus:
        # Section 57: same-focus transition is a deterministic NOOP,
        # never a fabricated full transition plan.
        return FocusTransitionPlan(
            schema_version=FOCUS_TRANSITION_SCHEMA_VERSION,
            from_focus=from_focus, to_focus=to_focus, status="NOOP",
            prerequisites=[], resource_changes=[], lifecycle_changes=[],
            conflicts=[], blockers=[], warnings=[],
            expected_ram_reclaim_bytes=None, expected_vram_reclaim_bytes=None,
            reclaim_confidence="unknown", reversible=True, cost="low",
        )

    to_policy = build_focus_policy(to_focus, evidence)

    prerequisites: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []

    if to_policy.readiness != "available":
        prerequisites.append(
            f"{to_focus} readiness is '{to_policy.readiness}': {to_policy.rationale}"
        )
    if to_policy.readiness == "blocked":
        blockers.append(
            f"{to_focus} cannot be realized yet - see its own readiness reason above "
            "(Section 42: this is reported honestly rather than pretending a "
            "privacy/other focus can be realized)."
        )

    if to_focus == "private" or from_focus == "private":
        warnings.append(
            "Private focus preserves every S6 invariant regardless of this "
            "transition: no global Tor routing, no global DNS mutation, no "
            "direct Whonix-Workstation clearnet egress (Section 43/55/106)."
        )
    if to_focus == "private":
        warnings.append(
            "Any other domain's GPU/resource preference must never interfere "
            "with privacy isolation invariants (Section 55)."
        )
    if from_focus == "private" and to_focus != "private":
        warnings.append(
            "Leaving private focus does not automatically discard any active "
            "private workspace/session state - explicit lifecycle handling "
            "remains future work (Section 56); S6.5 only reports this, it "
            "never destroys state."
        )

    resource_changes = _domain_resource_changes(from_policy, to_policy)
    gpu_change = _gpu_resource_change(from_policy, to_policy)
    if gpu_change is not None:
        resource_changes.append(gpu_change)

    lifecycle_changes = [
        intent for intent in to_policy.lifecycle_intents if intent.status == "APPLY"
    ]

    conflicts = to_policy.conflicts

    status = "BLOCKED" if to_policy.readiness == "blocked" else "PLANNABLE"
    cost = "low"
    for intent in lifecycle_changes:
        if _COST_RANK[intent.cost] > _COST_RANK[cost]:
            cost = intent.cost

    return FocusTransitionPlan(
        schema_version=FOCUS_TRANSITION_SCHEMA_VERSION,
        from_focus=from_focus, to_focus=to_focus, status=status,
        prerequisites=prerequisites, resource_changes=resource_changes,
        lifecycle_changes=lifecycle_changes, conflicts=conflicts,
        blockers=blockers, warnings=warnings,
        expected_ram_reclaim_bytes=None, expected_vram_reclaim_bytes=None,
        reclaim_confidence="unknown", reversible=True, cost=cost,
    )


def build_focus_transition_plan(
    from_focus: str,
    to_focus: str,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
    home: Path | None = None,
) -> FocusTransitionPlan:
    evidence = gather_focus_evidence(root=root, runner=runner, home=home)
    return build_focus_transition(from_focus, to_focus, evidence)
