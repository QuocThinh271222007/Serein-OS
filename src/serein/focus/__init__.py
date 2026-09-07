"""Serein Focus subsystem (S6.5): one-primary-focus architecture,
domain readiness, resource intent, and transition planning across the
development/AI/cyber/private domains. No Apply engine exists - see
docs/focus/architecture.md.

Many domains may exist simultaneously; Serein may have at most one
PRIMARY focus at any moment, and PRIMARY never means EXCLUSIVE
(ADR-0025)."""

from __future__ import annotations

from serein.focus.models import (
    FOCUS_CAPABILITIES_SCHEMA_VERSION,
    FOCUS_PLAN_SCHEMA_VERSION,
    FOCUS_TRANSITION_SCHEMA_VERSION,
    FocusPolicy,
    FocusTransitionPlan,
)
from serein.focus.planner import build_focus_plan
from serein.focus.transition import build_focus_transition_plan

__all__ = [
    "FOCUS_CAPABILITIES_SCHEMA_VERSION",
    "FOCUS_PLAN_SCHEMA_VERSION",
    "FOCUS_TRANSITION_SCHEMA_VERSION",
    "FocusPolicy",
    "FocusTransitionPlan",
    "build_focus_plan",
    "build_focus_transition_plan",
]
