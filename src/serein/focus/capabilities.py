"""``serein focus capabilities``: which planning/lifecycle mechanisms
Serein's Focus subsystem can describe today, and whether each is
merely *available* to detect, *plannable* (S6.5 can compute an intent
for it), or genuinely *enforceable* (Section 18) - S6.5 has no Apply
engine, so ``enforceable=False`` for nearly everything is expected and
correct, not a gap.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.focus.evidence import gather_focus_evidence
from serein.focus.models import (
    FOCUS_CAPABILITIES_SCHEMA_VERSION,
    FocusCapabilitiesReport,
)
from serein.focus.models import FocusCapability as Capability
from serein.hardware._util import DEFAULT_ROOT


def build_focus_capabilities(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> FocusCapabilitiesReport:
    evidence = gather_focus_evidence(root=root, runner=runner, home=home)
    gpu_present = bool(evidence.hardware.gpu)

    capabilities: list[Capability] = [
        Capability(
            "cpu_weight_planning", True, True, False,
            "systemd CPUWeight (future)", "high",
            "Relative CPU scheduling-preference intent can always be planned "
            "from domain roles; nothing is enforced (Section 19-21).",
        ),
        Capability(
            "memory_budget_planning", True, True, False,
            "systemd MemoryHigh (future, soft pressure only)", "high",
            "Qualitative memory-budget intent (system reserve, primary/"
            "secondary target) can always be planned; MemoryMax is never a "
            "default mechanism (Section 23-24).",
        ),
        Capability(
            "io_weight_planning", True, True, False,
            "systemd IOWeight (future)", "medium",
            "Relative I/O preference intent can be planned; never a "
            "throughput reservation (Section 28).",
        ),
        Capability(
            "gpu_lease_intent", gpu_present, True, False,
            "vendor-specific runtime only - no generic cross-vendor "
            "mechanism exists (Section 29-30)", "medium" if gpu_present else "high",
            "GPU lease intent can be described whenever a GPU is present "
            "(S2 evidence); generic enforcement is never claimed."
            if gpu_present else "No GPU device detected - no lease intent to plan.",
        ),
        Capability(
            "service_lifecycle_planning", True, True, False,
            "systemd unit inspection (future) - reused from S4's own "
            "detection, never a second detector", "high",
            "Lifecycle candidates (KEEP/QUIESCE_CANDIDATE/etc.) can be "
            "planned for Serein-understood services (e.g. the local AI "
            "runtime); no service is ever started/stopped (Section 36-38).",
        ),
        Capability(
            "container_lifecycle_planning", True, True, False,
            "reused from S3/S5 container detection", "high",
            "Lifecycle candidates can be planned for the isolated cyber "
            "toolbox; no container is ever created/stopped (Section 39).",
        ),
        Capability(
            "vm_lifecycle_planning", True, True, False,
            "reused from S5 VM readiness / S6 Whonix readiness", "high",
            "Lifecycle candidates can be planned for cyber/Whonix VM "
            "readiness; no VM is ever started/stopped (Section 40).",
        ),
        Capability(
            "thermal_constraint_awareness", evidence.thermal_zone_count > 0, True, False,
            "reused from S2 thermal detection", "high",
            f"{evidence.thermal_zone_count} thermal zone(s) detected - used "
            "only to report a constraint, never to invent headroom "
            "(Section 61)." if evidence.thermal_zone_count
            else "No thermal telemetry available - no headroom is assumed.",
        ),
        Capability(
            "battery_constraint_awareness", evidence.battery_present, True, False,
            "reused from S2 power-policy detection", "high",
            "A battery is present - focus intent can note a "
            "battery-efficiency conflict (Section 62)." if evidence.battery_present
            else "No battery detected - no battery constraint to report.",
        ),
        Capability(
            "privacy_boundary_awareness", True, True, False,
            "reused from S6 Veil capabilities", "high",
            "Private focus readiness/constraints are always derived from "
            "S6's own Tor/Whonix/workspace evidence, never re-detected "
            "(Section 15/41-43).",
        ),
        Capability(
            "transition_simulation", True, True, False,
            "build_focus_transition() (deterministic, evidence-only)", "high",
            "Every canonical focus-target pair can be simulated "
            "(Section 51-58/100); no transition is ever executed.",
        ),
    ]

    return FocusCapabilitiesReport(
        schema_version=FOCUS_CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities
    )
