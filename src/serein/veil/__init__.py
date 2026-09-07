"""Serein privacy-isolation workspace subsystem (S6): Tor client, Tor
Browser, DNS-leak, private-workspace, and Whonix capability modeling
and deterministic planning. No Apply mechanism exists - see
docs/veil/architecture.md.

Privacy is an explicit, opt-in workspace boundary, never an invisible
global side effect: normal host networking remains normal unless the
user explicitly enters a Veil workspace (docs/veil/threat-model.md)."""

from __future__ import annotations

from serein.veil.models import VEIL_CAPABILITIES_SCHEMA_VERSION, VEIL_PLAN_SCHEMA_VERSION, VeilPlan
from serein.veil.planner import build_veil_plan

__all__ = [
    "VEIL_CAPABILITIES_SCHEMA_VERSION",
    "VEIL_PLAN_SCHEMA_VERSION",
    "VeilPlan",
    "build_veil_plan",
]
