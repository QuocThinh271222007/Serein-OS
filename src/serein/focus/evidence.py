"""The Focus evidence aggregator (Section 87-88).

One central layer collects every existing subsystem's own read-only
output - S2 hardware, S3 development, S4 AI, S5 cyber, S6 veil - so
``policy.py``/``capabilities.py``/``transition.py``/``doctor.py`` all
compute focus semantics from the exact same snapshot instead of each
independently re-running (and potentially disagreeing about) detection.
This module never re-implements a single detector - it only calls each
subsystem's own top-level, already-correct ``build_*_capabilities()``/
``probe_hardware()`` entry point (Section 11-15).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from serein.ai.capabilities import build_ai_capabilities
from serein.ai.models import AICapabilitiesReport
from serein.cyber.capabilities import build_cyber_capabilities
from serein.cyber.models import CyberCapabilitiesReport
from serein.development.capabilities import build_development_capabilities
from serein.development.models import DevelopmentCapabilitiesReport
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.capabilities import build_capabilities
from serein.hardware.models import CapabilitiesReport as HardwareCapabilitiesReport
from serein.hardware.models import HardwareReport
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.thermal import detect_thermal
from serein.veil.capabilities import build_veil_capabilities
from serein.veil.models import VeilCapabilitiesReport


@dataclass(frozen=True)
class FocusEvidence:
    """Every subsystem snapshot a focus policy/transition/capability
    computation may read - gathered exactly once per CLI invocation,
    never re-derived independently by a downstream module (Section 88).
    """

    hardware: HardwareReport
    hardware_capabilities: HardwareCapabilitiesReport
    development_capabilities: DevelopmentCapabilitiesReport
    ai_capabilities: AICapabilitiesReport
    cyber_capabilities: CyberCapabilitiesReport
    veil_capabilities: VeilCapabilitiesReport
    #: Section 61-62: thermal/battery evidence for constraint
    #: reporting - reused from S2 directly, never re-detected.
    thermal_zone_count: int
    battery_present: bool


def gather_focus_evidence(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> FocusEvidence:
    hardware = probe_hardware(root)
    thermal = detect_thermal(root)
    power = detect_power_policy(root)
    return FocusEvidence(
        hardware=hardware,
        hardware_capabilities=build_capabilities(root),
        development_capabilities=build_development_capabilities(root, runner, home),
        ai_capabilities=build_ai_capabilities(root, runner),
        cyber_capabilities=build_cyber_capabilities(root, runner),
        veil_capabilities=build_veil_capabilities(root, runner, home),
        thermal_zone_count=len(thermal.zones),
        battery_present=bool(power.batteries),
    )
