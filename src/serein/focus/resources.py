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

#: S6.5R Corrective C, Section 18/45: the only S4 evidence strong
#: enough to justify AI GPU *preference* - generic hardware/driver/
#: runtime presence (nvidia_hardware, nvidia_driver, cuda_runtime,
#: rocm_runtime) is deliberately never sufficient (Section 19/45).
_USABLE_AI_GPU_BACKEND_IDS: tuple[str, ...] = ("pytorch_cuda", "pytorch_rocm")


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


def usable_ai_gpu_backend(evidence: FocusEvidence) -> bool:
    """S6.5R Corrective C (Section 18/44-45): the sole gate for AI GPU
    *preference* - a confirmed-usable S4 GPU-backed PyTorch build.
    Generic hardware presence, driver presence, or CUDA/ROCm *runtime*
    presence are all deliberately insufficient (Section 19/45) - each
    of those can be true while the actual application-level backend
    (what Serein's own S4 ``select_pytorch_backend()`` decision
    reflects) remains unusable."""
    by_id = {c.id: c for c in evidence.ai_capabilities.capabilities}
    return any(
        by_id.get(capability_id) is not None and by_id[capability_id].usable is True
        for capability_id in _USABLE_AI_GPU_BACKEND_IDS
    )


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
        if usable_ai_gpu_backend(evidence):
            return GPULeaseIntent(
                preferred_domain="ai", mode="preferred", release_candidates=[],
                conflicting_domains=[], enforceable=False,
                mechanism="vendor-specific runtime only - no generic, cross-vendor "
                "GPU-cgroup-owner mechanism exists on Linux (Section 29-30)",
                confidence="low",
                reason="AI is the requested primary focus and a confirmed-usable "
                "S4 GPU-backed PyTorch build (CUDA or ROCm) is present (S4 "
                "evidence); Serein cannot enforce this preference with any "
                "generic mechanism, so it stays a planning-only lease intent, "
                "never exclusive (Section 18-20/30).",
            )
        return GPULeaseIntent(
            preferred_domain=None, mode="shared", enforceable=False, confidence="medium",
            reason="A GPU is present, but no S4 GPU-backed AI backend "
            "(pytorch_cuda/pytorch_rocm) is confirmed usable - generic GPU "
            "hardware, driver, or CUDA/ROCm runtime presence alone never "
            "justifies AI GPU preference (S6.5R Corrective C, Section "
            "18-19/45); AI focus remains valid CPU-only, but GPU lease stays "
            "shared until a real, usable backend is confirmed.",
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
# Service / container / VM lifecycle (S6.5R Corrective A/B, Section 2-16/
# 36-42/58-60)
#
# Mechanism availability, instance existence, instance running state, and
# Serein ownership are four genuinely separate facts, never collapsed into
# one boolean (Section 3). S6.5 never adds a new instance-level detector
# (Section 42) - `podman ps`/`virsh list`/`systemctl status <service>` and
# equivalents are all out of scope - so `instance_present` stays `None`
# (genuinely unknown) for every target except `ai_runtime`, where the
# runtime *binary itself* is the recognized instance (Section 5/38): a
# single global runtime, not a per-workload container/VM S6.5 would need a
# dedicated detector to observe. `managed_by_serein` is `False` everywhere
# - no Apply engine has ever run, so Serein has created/owns nothing yet
# (Section 13-14).
# ---------------------------------------------------------------------------


def _ai_runtime_lifecycle(role: DomainRole, evidence: FocusEvidence) -> LifecycleIntent:
    """AI runtime binary presence (S4 `ollama`/`llama_cpp` capability
    `installed`) proves a tool exists - never that a daemon is running
    or a model is loaded (Section 5/37-38): `instance_running` stays
    `None` regardless of `instance_present`."""
    ollama = _capability_by_id(evidence.ai_capabilities.capabilities, "ollama")
    llama_cpp = _capability_by_id(evidence.ai_capabilities.capabilities, "llama_cpp")
    binary_present = bool((ollama and ollama.installed) or (llama_cpp and llama_cpp.installed))
    reason_prefix = "Local AI runtime (Ollama/llama.cpp, S4 evidence)"

    if not binary_present:
        return LifecycleIntent(
            kind="service", target="ai_runtime", domain=role.domain,
            recognized_by_serein=True, mechanism_available=False,
            instance_present=False, instance_running=None, managed_by_serein=False,
            target_intent="KEEP", reversible=True, cost="low",
            reason=f"{reason_prefix} is not detected - nothing to plan.",
            status="SKIP",
        )

    if role.state == "primary":
        return LifecycleIntent(
            kind="service", target="ai_runtime", domain=role.domain,
            recognized_by_serein=True, mechanism_available=True,
            instance_present=True, instance_running=None, managed_by_serein=False,
            target_intent="PRIORITY_CANDIDATE", reversible=True, cost="low",
            reason=f"{reason_prefix} is installed and {role.domain} is the "
            "primary focus - a priority candidate for a future runtime; "
            "S6.5 never starts, stops, or reconfigures it. Whether a daemon "
            "is actually running or a model is loaded remains unknown - "
            "binary presence is never read as running state (Section 37).",
            status="APPLY",
        )
    if role.state == "secondary":
        return LifecycleIntent(
            kind="service", target="ai_runtime", domain=role.domain,
            recognized_by_serein=True, mechanism_available=True,
            instance_present=True, instance_running=None, managed_by_serein=False,
            target_intent="KEEP", reversible=True, cost="low",
            reason=f"{reason_prefix} is installed and {role.domain} is "
            "secondary - kept as-is, no change candidate.",
            status="NOOP",
        )
    # idle or off - a future runtime could reduce/quiesce it, never
    # destructively (Section 117: quiesce/unload, never delete). Valid
    # here because instance_present=True (Section 36 invariant).
    return LifecycleIntent(
        kind="service", target="ai_runtime", domain=role.domain,
        recognized_by_serein=True, mechanism_available=True,
        instance_present=True, instance_running=None, managed_by_serein=False,
        target_intent="QUIESCE_CANDIDATE", reversible=True, cost="medium",
        reason=f"{reason_prefix} is installed but {role.domain} is "
        f"{role.state} for this focus - a future runtime could quiesce it "
        "to free resources for the primary focus; S6.5 never executes "
        "this, and never proposes deleting any state.",
        status="APPLY",
    )


def _mechanism_only_lifecycle(
    kind: str, target_name: str, role: DomainRole, mechanism_available: bool, reason_prefix: str
) -> LifecycleIntent:
    """For targets where S6.5 has mechanism-readiness evidence but no
    instance-level detector (cyber toolbox, cyber VM, Whonix - Section
    6-9/39-41): `instance_present` stays `None` regardless of mechanism
    state, and `target_intent` stays `KEEP` in every case - an instance-
    level intent (QUIESCE_CANDIDATE/PRIORITY_CANDIDATE/etc.) is never
    proposed without `instance_present is True` (Section 4/36/60)."""
    if not mechanism_available:
        return LifecycleIntent(
            kind=kind, target=target_name, domain=role.domain,
            recognized_by_serein=True, mechanism_available=False,
            instance_present=None, instance_running=None, managed_by_serein=False,
            target_intent="KEEP", reversible=True, cost="low",
            reason=f"{reason_prefix} - mechanism is not available; nothing to plan.",
            status="SKIP",
        )
    return LifecycleIntent(
        kind=kind, target=target_name, domain=role.domain,
        recognized_by_serein=True, mechanism_available=True,
        instance_present=None, instance_running=None, managed_by_serein=False,
        target_intent="KEEP", reversible=True, cost="low",
        reason=f"{reason_prefix} - mechanism is available, but Serein has no "
        "instance-level detector for this target (S6.5R Corrective A, "
        "Section 6-9/39-42) - mechanism readiness alone never justifies a "
        "quiesce/priority/resource-increase/resource-reduce candidate "
        f"against a concrete instance, regardless of {role.domain}'s "
        f"current focus role ({role.state}).",
        status="NOOP",
    )


def build_lifecycle_intents(
    domain_roles: list[DomainRole], evidence: FocusEvidence
) -> list[LifecycleIntent]:
    roles_by_domain = {role.domain: role for role in domain_roles}
    intents: list[LifecycleIntent] = []

    intents.append(_ai_runtime_lifecycle(roles_by_domain["ai"], evidence))

    cyber_toolbox = _capability_by_id(evidence.cyber_capabilities.capabilities, "container_toolbox")
    intents.append(
        _mechanism_only_lifecycle(
            "container", "cyber_toolbox", roles_by_domain["cyber"],
            bool(cyber_toolbox and cyber_toolbox.installed),
            "Isolated cyber toolbox mechanism (S5 evidence: container "
            "engine + Distrobox present) - this is engine/tool presence, "
            "never proof a toolbox container instance was ever created",
        )
    )

    cyber_vm = _capability_by_id(evidence.cyber_capabilities.capabilities, "vm_isolation")
    intents.append(
        _mechanism_only_lifecycle(
            "vm", "cyber_vm", roles_by_domain["cyber"],
            bool(cyber_vm and cyber_vm.usable),
            "Cyber VM backend mechanism (S5 evidence: KVM/QEMU/libvirt "
            "readiness) - this is backend readiness, never proof a cyber VM "
            "was ever created",
        )
    )

    whonix_boundary = _capability_by_id(
        evidence.veil_capabilities.capabilities, "vm_privacy_boundary"
    )
    whonix_artifacts = _capability_by_id(evidence.veil_capabilities.capabilities, "whonix_vm")
    whonix_mechanism_available = bool(whonix_boundary and whonix_boundary.usable)
    whonix_reason_prefix = (
        "Whonix VM backend mechanism (S6 evidence: VM privacy boundary "
        "readiness, reused from S5) - this is backend readiness, never "
        "proof a Whonix VM was ever imported/defined/run"
    )
    if whonix_artifacts and whonix_artifacts.installed:
        whonix_reason_prefix += (
            "; Gateway/Workstation qcow2 artifacts are present, but "
            "artifact presence alone never proves VM import, definition, "
            "or running-instance existence (Section 8)"
        )
    intents.append(
        _mechanism_only_lifecycle(
            "vm", "whonix", roles_by_domain["private"],
            whonix_mechanism_available, whonix_reason_prefix,
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
