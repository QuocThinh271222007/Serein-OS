"""Resource-intent construction: CPU/IO weight intents, memory budget
intent, GPU lease intent, service/container/VM lifecycle intents, and
conflict identification (Section 9/19-40/49-60).

Every builder here is a pure function of ``(domain roles, evidence)`` -
no detection happens in this module, only translation of already-
gathered S2-S6 evidence into planning-only intent objects. Nothing here
ever executes a command.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from serein.focus.evidence import FocusEvidence
from serein.focus.models import (
    RELATIVE_WEIGHTS,
    DomainRole,
    FocusConflict,
    GPULeaseIntent,
    LifecycleIntent,
    MemoryBudgetIntent,
    ResourceIntent,
)


class _CapabilityLike(Protocol):
    """Structural shape shared by AICapability/CyberCapability/
    VeilCapability - the only fields this module ever reads from a
    looked-up capability."""

    id: str
    installed: bool
    usable: bool | None


def _capability_by_id(
    capabilities: Sequence[_CapabilityLike], capability_id: str
) -> _CapabilityLike | None:
    for capability in capabilities:
        if capability.id == capability_id:
            return capability
    return None


# ---------------------------------------------------------------------------
# CPU / IO (Section 19-22)
# ---------------------------------------------------------------------------


def build_resource_intents(domain_roles: list[DomainRole]) -> list[ResourceIntent]:
    """Relative CPUWeight/IOWeight-style intent only (Section 19-20) -
    never a percentage, never a hard CPUQuota= (Section 21), never a
    CPU affinity mask (Section 22 - ``cpu_affinity_intent`` is
    deliberately absent from this model, not merely ``None``, since
    S6.5 has no per-core topology evidence to justify one)."""
    intents: list[ResourceIntent] = []
    for role in domain_roles:
        weight = RELATIVE_WEIGHTS[role.state]
        for resource, mechanism in (
            ("cpu", "systemd CPUWeight (future) - a relative scheduling "
             "preference during contention, never a CPU percentage or "
             "quota (Section 19-20)"),
            ("io", "systemd IOWeight (future) - a relative I/O preference, "
             "never an MB/s throughput guarantee (Section 28)"),
        ):
            intents.append(
                ResourceIntent(
                    resource=resource,
                    domain=role.domain,
                    priority=role.state,
                    relative_weight=weight if role.state != "off" else None,
                    mechanism=mechanism,
                    enforceable=False,
                    confidence="low",
                    reason=(
                        f"{role.domain} is {role.state} for this focus target; "
                        "relative weight intent only, never enforced by S6.5 "
                        "(no Apply engine exists)."
                    ),
                )
            )
    return intents


# ---------------------------------------------------------------------------
# Memory (Section 23-27)
# ---------------------------------------------------------------------------


def build_memory_intent(
    domain_roles: list[DomainRole], evidence: FocusEvidence
) -> MemoryBudgetIntent:
    has_primary = any(role.state == "primary" for role in domain_roles)
    has_secondary = any(role.state == "secondary" for role in domain_roles)
    idle_domains = [role.domain for role in domain_roles if role.state == "idle"]

    confidence = "medium" if evidence.hardware.memory.total_bytes else "low"
    return MemoryBudgetIntent(
        system_reserve=(
            "protected - kernel/desktop/display-server/audio/input/shell/"
            "system-service reserve is never claimed by a focus domain "
            "(Section 64-65); no policy assigns 100% of detected RAM."
        ),
        primary_target="high" if has_primary else "none",
        secondary_target="medium" if has_secondary else "low",
        reclaim_candidates=[f"{domain} (idle workload)" for domain in idle_domains],
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# GPU (Section 29-35)
# ---------------------------------------------------------------------------


def build_gpu_intent(domain_roles: list[DomainRole], evidence: FocusEvidence) -> GPULeaseIntent:
    gpu_present = bool(evidence.hardware.gpu)
    if not gpu_present:
        return GPULeaseIntent(
            preferred_domain=None, mode="unavailable", enforceable=False, confidence="high",
            reason="No GPU device detected on this host (S2 evidence) - there is "
            "nothing to lease.",
        )

    primary = next((role for role in domain_roles if role.state == "primary"), None)
    if primary is not None and primary.domain == "ai":
        return GPULeaseIntent(
            preferred_domain="ai", mode="preferred", release_candidates=[],
            conflicting_domains=[], enforceable=False,
            mechanism="vendor-specific runtime only - no generic, cross-vendor "
            "GPU-cgroup-owner mechanism exists on Linux (Section 29-30)",
            confidence="low",
            reason="AI is the requested primary focus and a GPU device is "
            "present (S2/S4 evidence); Serein cannot enforce this preference "
            "with any generic mechanism, so it stays a planning-only lease "
            "intent, never exclusive (Section 30).",
        )

    # dev/cyber/private/balanced: shared by default (Section 32-34) - GPU
    # preference is never claimed just because a domain became primary.
    return GPULeaseIntent(
        preferred_domain=None, mode="shared", enforceable=False, confidence="medium",
        reason="A GPU is present, but no domain requires preferred/exclusive "
        "access by default for this focus target (Section 32-34) - Cyber "
        "does not automatically claim the GPU, Dev stays shared unless a "
        "compute/render workload is known, and Private never seeks GPU "
        "passthrough for performance.",
    )


# ---------------------------------------------------------------------------
# Service / container / VM lifecycle (Section 36-40, 82-83, 117)
# ---------------------------------------------------------------------------


def _lifecycle_for_target(
    kind: str, target_name: str, role: DomainRole, installed: bool, reason_prefix: str
) -> LifecycleIntent:
    current_state = "available" if installed else "not_detected"
    if not installed:
        return LifecycleIntent(
            kind, target_name, role.domain, current_state, "KEEP",
            managed_by_serein=True, reversible=True, cost="low",
            reason=f"{reason_prefix} is not detected - nothing to plan.",
            status="SKIP",
        )
    if role.state == "primary":
        return LifecycleIntent(
            kind, target_name, role.domain, current_state, "PRIORITY_CANDIDATE",
            managed_by_serein=True, reversible=True, cost="low",
            reason=f"{reason_prefix} is installed and {role.domain} is the "
            "primary focus - a priority candidate for a future runtime; "
            "S6.5 never starts, stops, or reconfigures it.",
            status="APPLY",
        )
    if role.state == "secondary":
        return LifecycleIntent(
            kind, target_name, role.domain, current_state, "KEEP",
            managed_by_serein=True, reversible=True, cost="low",
            reason=f"{reason_prefix} is installed and {role.domain} is "
            "secondary - kept as-is, no change candidate.",
            status="NOOP",
        )
    # idle or off - a future runtime could reduce/quiesce it, never
    # destructively (Section 117: quiesce/unload, never delete).
    return LifecycleIntent(
        kind, target_name, role.domain, current_state, "QUIESCE_CANDIDATE",
        managed_by_serein=True, reversible=True, cost="medium",
        reason=f"{reason_prefix} is installed but {role.domain} is "
        f"{role.state} for this focus - a future runtime could quiesce it "
        "to free resources for the primary focus; S6.5 never executes "
        "this, and never proposes deleting any state.",
        status="APPLY",
    )


def build_lifecycle_intents(
    domain_roles: list[DomainRole], evidence: FocusEvidence
) -> list[LifecycleIntent]:
    roles_by_domain = {role.domain: role for role in domain_roles}
    intents: list[LifecycleIntent] = []

    ai_ollama = _capability_by_id(evidence.ai_capabilities.capabilities, "ollama")
    ai_llama_cpp = _capability_by_id(evidence.ai_capabilities.capabilities, "llama_cpp")
    ai_runtime_installed = bool(
        (ai_ollama and ai_ollama.installed) or (ai_llama_cpp and ai_llama_cpp.installed)
    )
    intents.append(
        _lifecycle_for_target(
            "service", "ai_runtime", roles_by_domain["ai"], ai_runtime_installed,
            "Local AI runtime (Ollama/llama.cpp, S4 evidence)",
        )
    )

    cyber_toolbox = _capability_by_id(evidence.cyber_capabilities.capabilities, "container_toolbox")
    intents.append(
        _lifecycle_for_target(
            "container", "cyber_toolbox", roles_by_domain["cyber"],
            bool(cyber_toolbox and cyber_toolbox.installed),
            "Isolated cyber toolbox (S5 evidence)",
        )
    )

    cyber_vm = _capability_by_id(evidence.cyber_capabilities.capabilities, "vm_isolation")
    intents.append(
        _lifecycle_for_target(
            "vm", "cyber_vm", roles_by_domain["cyber"],
            bool(cyber_vm and cyber_vm.usable),
            "Cyber VM isolation (S5 evidence)",
        )
    )

    whonix = _capability_by_id(evidence.veil_capabilities.capabilities, "whonix_vm")
    intents.append(
        _lifecycle_for_target(
            "vm", "whonix", roles_by_domain["private"],
            bool(whonix and whonix.installed),
            "Whonix Gateway/Workstation (S6 evidence)",
        )
    )

    return intents


# ---------------------------------------------------------------------------
# Conflicts (Section 59-60)
# ---------------------------------------------------------------------------


def build_conflicts(gpu_intent: GPULeaseIntent) -> list[FocusConflict]:
    """Populated only from real, already-gathered evidence
    (``gpu_intent.conflicting_domains``) - never fabricated. Empty in
    every S6.5 build today, since Serein has no live GPU-utilization
    evidence to name a genuine conflicting domain (Section 70: an
    empty, explained list is preferred over an invented one)."""
    if not gpu_intent.conflicting_domains:
        return []
    return [
        FocusConflict(
            resource="gpu",
            domains=[
                d for d in (gpu_intent.preferred_domain, *gpu_intent.conflicting_domains) if d
            ],
            severity="medium",
            resolution="GPU stays shared; no domain is forcibly evicted (Section 60).",
            automatic=True,
            reason="Multiple domains have GPU-relevant evidence; Serein never "
            "resolves this destructively.",
        )
    ]


# ---------------------------------------------------------------------------
# Constraints (Section 61-65)
# ---------------------------------------------------------------------------


def build_constraints(evidence: FocusEvidence) -> list[str]:
    constraints = [
        "System/desktop interactive responsiveness is part of the system "
        "reserve at every focus target (Section 64-65) - no policy grants "
        "100% CPU/RAM to a focus domain.",
    ]
    if evidence.thermal_zone_count == 0:
        constraints.append(
            "Thermal telemetry is unavailable on this host - no thermal "
            "headroom is assumed or invented; kernel/hardware thermal "
            "protection is never overridden (Section 61)."
        )
    else:
        constraints.append(
            "Thermal telemetry is available; performance intent stays "
            "subordinate to thermal safety regardless (Section 61)."
        )
    if evidence.battery_present:
        constraints.append(
            "A battery is present - a requested high-performance focus may "
            "conflict with battery-efficiency policy; S6.5 reports this "
            "conflict, it does not force maximum performance (Section 62)."
        )
    return constraints
