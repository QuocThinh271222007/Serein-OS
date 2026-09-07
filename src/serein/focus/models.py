"""Structured representations for the Focus subsystem (S6.5).

Mirrors the pattern S2-S6 established - dataclasses only, no behavior,
no runtime dependency on any scheduler/cgroup/service mechanism. See
docs/focus/architecture.md.

The governing principle (ADR-0025/0026): Serein may have at most one
PRIMARY focus domain at any moment, but PRIMARY never means EXCLUSIVE -
other domains keep running, and Serein only ever *plans* resource
intent (``docs/focus/resource-intent.md``); it never mutates a cgroup,
a systemd unit, a service, a container, a VM, a GPU, or a power
profile in this phase. Every field here is designed so that "planned
intent" never gets read as "enforced state" - ``enforceable=False`` is
the honest default almost everywhere, and a value is never fabricated
with false numeric precision (Section 25/84).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FOCUS_CAPABILITIES_SCHEMA_VERSION = 1
FOCUS_PLAN_SCHEMA_VERSION = 1
FOCUS_TRANSITION_SCHEMA_VERSION = 1

#: "balanced" is a valid plan/transition target (Section 5) - it means
#: "no professional domain owns primary-focus preference", never "a
#: fifth domain". FOCUS_DOMAINS below is the four real professional
#: domains only.
FOCUS_TARGETS: tuple[str, ...] = ("balanced", "dev", "ai", "cyber", "private")

#: The four professional domains S6.5 models (Section 5).
FOCUS_DOMAINS: tuple[str, ...] = ("dev", "ai", "cyber", "private")

#: Section 6: S6.5 models PRIMARY/SECONDARY/IDLE/OFF only - no
#: SUSPENDED (which would imply observed runtime state S6.5 never
#: collects).
DOMAIN_STATES: tuple[str, ...] = ("primary", "secondary", "idle", "off")

#: Section 76: every domain's capability readiness, distinct from its
#: DOMAIN_STATE (which is about focus preference, not availability).
READINESS_STATES: tuple[str, ...] = ("available", "limited", "blocked", "unknown")

#: Section 10: safety/reserve tiers are structural, not per-domain: a
#: DomainRole's own priority label only ever comes from this smaller
#: vocabulary (Section 19's CPUWeight/IOWeight table keys).
PRIORITY_LEVELS: tuple[str, ...] = ("primary", "secondary", "idle", "off")

#: Section 19/20: relative systemd CPUWeight/IOWeight-style scheduling
#: weights - NOT a CPU/IO percentage or throughput guarantee. Purely a
#: relative preference expressed during contention.
RELATIVE_WEIGHTS: dict[str, int] = {"primary": 1000, "secondary": 300, "idle": 80, "off": 0}

#: Section 10: the full, structural resource precedence order. User
#: focus preference (tiers 4-7) never outranks tiers 1-3.
RESOURCE_PRECEDENCE: tuple[str, ...] = (
    "system_safety_thermal",
    "privacy_security_boundary",
    "os_desktop_survival_reserve",
    "primary_focus",
    "secondary_workloads",
    "idle_workloads",
    "background_optional_work",
)

#: Section 30: GPU lease planning modes - "exclusive" is deliberately
#: never a value here (Section 30: avoid it unless real backend
#: enforcement exists, which S6.5 never implements).
GPU_LEASE_MODES: tuple[str, ...] = (
    "preferred", "shared", "release_requested", "unavailable", "unknown",
)

#: Section 36: lifecycle target-intent vocabulary.
LIFECYCLE_INTENTS: tuple[str, ...] = (
    "KEEP", "QUIESCE_CANDIDATE", "PRIORITY_CANDIDATE",
    "RESOURCE_INCREASE_CANDIDATE", "RESOURCE_REDUCE_CANDIDATE",
)

#: Reuses the exact S3-S6 plan-action status vocabulary (Section 36).
PLAN_STATUSES: tuple[str, ...] = ("APPLY", "NOOP", "SKIP", "BLOCKED")

#: Section 116: qualitative cost/reversibility labels - never a
#: fabricated time estimate.
COST_LEVELS: tuple[str, ...] = ("low", "medium", "high", "unknown")


@dataclass(frozen=True)
class DomainRole:
    """One professional domain's role within a single focus policy
    (Section 6-7). At most one ``DomainRole`` across a policy may have
    ``state == "primary"`` - enforced by ``evaluate_domain_roles()``
    and checked directly by the one-primary invariant tests/doctor
    check."""

    domain: str  # one of FOCUS_DOMAINS
    state: str  # one of DOMAIN_STATES
    readiness: str  # one of READINESS_STATES
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceIntent:
    """A single resource-plane preference for one domain (Section 9/50).
    ``relative_weight`` is only ever populated for ``cpu``/``io``
    (Section 19-20's CPUWeight/IOWeight concept) - never a percentage,
    never a throughput guarantee. ``enforceable`` is ``False`` in every
    build S6.5 ships (no Apply engine exists to enforce anything)."""

    resource: str  # "cpu" | "io"
    domain: str
    priority: str  # one of PRIORITY_LEVELS
    relative_weight: int | None
    mechanism: str | None
    enforceable: bool
    confidence: str  # "high" | "medium" | "low"
    reason: str
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryBudgetIntent:
    """Section 23-27: memory planning always preserves a system
    reserve and never allocates every detected byte to a focus domain.
    ``target_bytes`` stays ``None`` unless real, measured workload
    evidence exists (Section 25) - qualitative ``primary_target``/
    ``secondary_target`` labels are preferred over fake precision."""

    system_reserve: str  # qualitative, e.g. "protected"
    primary_target: str  # "high" | "medium" | "low" | "none"
    secondary_target: str
    reclaim_candidates: list[str] = field(default_factory=list)
    #: Always describes the *existing* S2 zram/swap mechanism - S6.5
    #: never rewrites zram-generator config or swappiness (Section 27).
    pressure_policy: str = "existing-zram-swap-policy (unchanged by S6.5)"
    confidence: str = "low"
    target_bytes: int | None = None
    mechanism: str = "systemd MemoryHigh (future, soft pressure only - Section 24)"
    enforceable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GPULeaseIntent:
    """Section 29-35: GPU *lease intent*, never generic cross-vendor
    enforcement - Linux has no universal "GPU cgroup owner" mechanism,
    so ``enforceable`` is always ``False`` here regardless of target."""

    preferred_domain: str | None  # one of FOCUS_DOMAINS, or None
    mode: str  # one of GPU_LEASE_MODES
    release_candidates: list[str] = field(default_factory=list)
    conflicting_domains: list[str] = field(default_factory=list)
    enforceable: bool = False
    mechanism: str | None = None
    confidence: str = "low"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleIntent:
    """Section 36-40: service/container/VM lifecycle planning, all
    sharing one shape (``kind`` distinguishes them) since their
    semantics and status vocabulary are identical. Only ever created
    for a target Serein *explicitly* understands via an existing
    subsystem's own detection (Section 37) - never an arbitrary
    process name."""

    kind: str  # "service" | "container" | "vm"
    target: str  # e.g. "ai_runtime", "cyber_toolbox", "cyber_vm", "whonix"
    domain: str  # one of FOCUS_DOMAINS
    current_state: str  # descriptive, e.g. "available" | "not_detected"
    target_intent: str  # one of LIFECYCLE_INTENTS
    managed_by_serein: bool
    reversible: bool | None
    cost: str  # one of COST_LEVELS
    reason: str
    status: str  # one of PLAN_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FocusConflict:
    """Section 59-60: a resource contention Serein has identified but
    never resolves destructively - ``automatic`` is only ever ``True``
    for a purely-planning-level resolution (e.g. "GPU stays shared"),
    never a resolution that stops/kills/reclaims anything."""

    resource: str
    domains: list[str]
    severity: str  # "low" | "medium" | "high"
    resolution: str
    automatic: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FocusPolicy:
    """The canonical, single-source-of-truth focus policy for one
    target (Section 49/88) - ``capabilities.py``, ``planner.py``,
    ``status.py``, and ``doctor.py`` all consume the same
    ``build_focus_policy()`` result rather than deriving domain roles/
    resource intent independently (avoiding the exact class of S5-style
    divergence bug S5R/S6R had to fix after the fact)."""

    schema_version: int
    target: str  # one of FOCUS_TARGETS
    primary_domain: str | None  # None only for "balanced"
    readiness: str  # one of READINESS_STATES - overall readiness for this target
    domain_roles: list[DomainRole]
    resource_intents: list[ResourceIntent]
    memory_intent: MemoryBudgetIntent
    gpu_intent: GPULeaseIntent
    lifecycle_intents: list[LifecycleIntent]
    conflicts: list[FocusConflict]
    constraints: list[str]
    rationale: str
    #: Always False in S6.5 - no Apply engine exists (Section 3-4/107).
    runtime_enforcement: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "primary_domain": self.primary_domain,
            "readiness": self.readiness,
            "domain_roles": [d.to_dict() for d in self.domain_roles],
            "resource_intents": [r.to_dict() for r in self.resource_intents],
            "memory_intent": self.memory_intent.to_dict(),
            "gpu_intent": self.gpu_intent.to_dict(),
            "lifecycle_intents": [lc.to_dict() for lc in self.lifecycle_intents],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "constraints": self.constraints,
            "rationale": self.rationale,
            "runtime_enforcement": self.runtime_enforcement,
        }


@dataclass(frozen=True)
class ResourceChange:
    """One resource-plane delta within a transition plan (Section 51)."""

    resource: str  # "cpu" | "memory" | "io" | "gpu"
    domain: str
    before: str | None  # qualitative label, e.g. "high"; None if n/a
    after: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FocusTransitionPlan:
    """Section 51-58: deterministic transition planning only -
    ``status`` is ``"NOOP"`` for ``from_focus == to_focus`` (Section
    57), ``"BLOCKED"`` if the target's own policy readiness is
    ``"blocked"``, otherwise ``"PLANNABLE"``. Never a mutation."""

    schema_version: int
    from_focus: str
    to_focus: str
    status: str  # "NOOP" | "PLANNABLE" | "BLOCKED"
    prerequisites: list[str]
    resource_changes: list[ResourceChange]
    lifecycle_changes: list[LifecycleIntent]
    conflicts: list[FocusConflict]
    blockers: list[str]
    warnings: list[str]
    #: Section 84-85/105: always None unless real, measured evidence
    #: exists - S6.5 never fabricates a precise reclaim number.
    expected_ram_reclaim_bytes: int | None
    expected_vram_reclaim_bytes: int | None
    reclaim_confidence: str  # always "unknown" in S6.5
    reversible: bool
    cost: str  # one of COST_LEVELS
    runtime_enforcement: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "from_focus": self.from_focus,
            "to_focus": self.to_focus,
            "status": self.status,
            "prerequisites": self.prerequisites,
            "resource_changes": [c.to_dict() for c in self.resource_changes],
            "lifecycle_changes": [lc.to_dict() for lc in self.lifecycle_changes],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "blockers": self.blockers,
            "warnings": self.warnings,
            "expected_ram_reclaim_bytes": self.expected_ram_reclaim_bytes,
            "expected_vram_reclaim_bytes": self.expected_vram_reclaim_bytes,
            "reclaim_confidence": self.reclaim_confidence,
            "reversible": self.reversible,
            "cost": self.cost,
            "runtime_enforcement": self.runtime_enforcement,
        }


@dataclass(frozen=True)
class FocusCapability:
    """Mirrors S4/S5/S6's capability shape, extended with the
    ``plannable``/``enforceable`` split Section 18 requires (S6.5 has
    no Apply engine, so ``enforceable=False`` is expected and correct
    for nearly everything)."""

    id: str
    available: bool | None
    plannable: bool
    enforceable: bool
    mechanism: str | None
    confidence: str  # "high" | "medium" | "low"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FocusCapabilitiesReport:
    schema_version: int
    capabilities: list[FocusCapability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass(frozen=True)
class FocusStatusReport:
    """Section 16-17: never fabricates an ``applied_focus`` - S6.5 has
    no Apply engine and no persistence, so ``applied_focus`` is always
    ``None`` and ``mode`` is always ``"planning_only"``."""

    schema_version: int
    mode: str  # always "planning_only" in S6.5
    runtime_enforcement: bool  # always False
    applied_focus: str | None  # always None in S6.5
    requested_focus: str | None
    policy_baseline: str  # always "balanced"
    supported_targets: list[str]
    domain_readiness: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
