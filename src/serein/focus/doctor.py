"""``serein focus doctor``: Focus-layer diagnostics.

Reuses ``serein.doctor.models`` (the same PASS/WARN/FAIL/SKIP model
every subsystem's doctor uses). A host with no GPU/KVM/Tor is never a
FAIL here (Section 91) - that is a capability limitation, not a
structural defect. FAIL is reserved for genuine internal
contradictions: more than one PRIMARY domain, an overclaimed GPU
enforcement, a private policy that would weaken a Veil invariant, a
plan that assigns zero system reserve, or an unknown transition target
(Section 92).
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.focus.domains import CANONICAL_TRANSITIONS
from serein.focus.evidence import FocusEvidence, gather_focus_evidence
from serein.focus.models import FOCUS_TARGETS
from serein.focus.policy import build_focus_policy
from serein.focus.transition import build_focus_transition
from serein.hardware._util import DEFAULT_ROOT

_ONE_PRIMARY_CHECK = ("focus_one_primary_invariant", "One-primary-domain invariant")
_DETERMINISM_CHECK = ("focus_policy_determinism", "Focus policy determinism")
_RESERVE_CHECK = ("focus_system_reserve_present", "System reserve present in every policy")
_GPU_CHECK = ("focus_gpu_not_overclaimed", "GPU enforcement not overclaimed")
_PRIVATE_INVARIANT_CHECK = (
    "focus_private_preserves_veil_invariants", "Private focus preserves Veil invariants",
)
_NO_MUTATION_CHECK = ("focus_plan_no_mutation", "Focus plan does not mutate host")
_TRANSITION_GRAPH_CHECK = ("focus_transition_graph_complete", "Transition graph complete")

_FORBIDDEN_MUTATION_MARKERS: tuple[str, ...] = (
    "kill", "pkill", "killall",
    "systemctl stop", "systemctl start", "systemctl set-property",
    "cgcreate", "cgset",
    "virsh start", "virsh shutdown", "virsh destroy",
    "podman stop", "docker stop",
    "nvidia-smi -pl", "nvidia-smi --gpu-reset", "rocm-smi --set",
    "powerprofilesctl set", "cpupower frequency-set",
    "drop_caches", "swapoff", "swapon",
    "ip netns add", "ip route", "nft ", "iptables", "resolvectl dns", "nmcli proxy",
)


def _check_one_primary(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _ONE_PRIMARY_CHECK
    for target in FOCUS_TARGETS:
        policy = build_focus_policy(target, evidence)
        primaries = [role.domain for role in policy.domain_roles if role.state == "primary"]
        if target == "balanced" and primaries:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"'balanced' produced a PRIMARY domain ({primaries}) - invariant violated.",
            )
        if target != "balanced" and primaries != [target]:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"target={target!r} produced primaries={primaries!r} "
                f"(expected exactly [{target!r}]).",
            )
    return CheckResult(
        check_id, title, CheckStatus.PASS,
        "Every target produces exactly the expected PRIMARY domain count (0 or 1).",
    )


def _check_determinism(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _DETERMINISM_CHECK
    for target in FOCUS_TARGETS:
        first = build_focus_policy(target, evidence).to_dict()
        second = build_focus_policy(target, evidence).to_dict()
        if first != second:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"target={target!r} produced two different policies from identical evidence.",
            )
    detail = "Identical evidence produces identical policies."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_system_reserve(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _RESERVE_CHECK
    for target in FOCUS_TARGETS:
        policy = build_focus_policy(target, evidence)
        if not policy.memory_intent.system_reserve:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"target={target!r} has an empty system_reserve - zero reserve is never valid.",
            )
    detail = "Every policy declares a non-empty system reserve."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_gpu_not_overclaimed(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _GPU_CHECK
    for target in FOCUS_TARGETS:
        policy = build_focus_policy(target, evidence)
        if policy.gpu_intent.enforceable:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"target={target!r} claims gpu_intent.enforceable=True - no generic "
                "cross-vendor GPU enforcement mechanism exists (Section 29-30).",
            )
        valid_modes = ("preferred", "shared", "release_requested", "unavailable", "unknown")
        if policy.gpu_intent.mode not in valid_modes:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"target={target!r} has an unrecognized GPU lease mode "
                f"{policy.gpu_intent.mode!r}.",
            )
    detail = "No policy claims generic GPU enforcement."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_private_preserves_veil_invariants(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _PRIVATE_INVARIANT_CHECK
    policy = build_focus_policy("private", evidence)
    haystack = " ".join(
        [policy.rationale, *policy.constraints, *(c.reason for c in policy.conflicts)]
    ).lower()
    forbidden = (
        "route entire host", "global tor routing", "direct clearnet", "disable veil isolation",
    )
    hit = next((marker for marker in forbidden if marker in haystack), None)
    if hit:
        return CheckResult(
            check_id, title, CheckStatus.FAIL,
            f"Private policy text contains forbidden phrase: {hit!r}.",
        )
    return CheckResult(
        check_id, title, CheckStatus.PASS, "Private focus policy text preserves Veil invariants."
    )


def _check_no_mutation(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _NO_MUTATION_CHECK
    for target in FOCUS_TARGETS:
        policy = build_focus_policy(target, evidence)
        haystack = " ".join(
            [
                policy.rationale,
                *policy.constraints,
                *(r.reason for r in policy.resource_intents),
                policy.memory_intent.system_reserve,
                policy.memory_intent.pressure_policy,
                policy.memory_intent.mechanism,
                policy.gpu_intent.reason,
                *(lc.reason for lc in policy.lifecycle_intents),
                *(c.reason for c in policy.conflicts),
            ]
        ).lower()
        hit = next((marker for marker in _FORBIDDEN_MUTATION_MARKERS if marker in haystack), None)
        if hit:
            return CheckResult(
                check_id, title, CheckStatus.FAIL,
                f"target={target!r} plan text contains a mutation-shaped marker: {hit!r}.",
            )
    detail = "No plan text contains a mutation-shaped marker."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_transition_graph(evidence: FocusEvidence) -> CheckResult:
    check_id, title = _TRANSITION_GRAPH_CHECK
    try:
        for from_focus, to_focus in CANONICAL_TRANSITIONS:
            build_focus_transition(from_focus, to_focus, evidence)
        for target in FOCUS_TARGETS:
            build_focus_transition(target, target, evidence)
    except Exception as exc:
        return CheckResult(check_id, title, CheckStatus.FAIL, f"Transition planning raised: {exc}")
    detail = (
        f"All {len(CANONICAL_TRANSITIONS)} canonical transitions plus same-target "
        "NOOPs planned without error."
    )
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def run_focus_checks(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> DoctorReport:
    evidence = gather_focus_evidence(root=root, runner=runner, home=home)
    checks = [
        _check_one_primary(evidence),
        _check_determinism(evidence),
        _check_system_reserve(evidence),
        _check_gpu_not_overclaimed(evidence),
        _check_private_preserves_veil_invariants(evidence),
        _check_no_mutation(evidence),
        _check_transition_graph(evidence),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
