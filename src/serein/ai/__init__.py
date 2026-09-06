"""Serein AI workstation subsystem (S4): hardware-backend classification,
NVIDIA/AMD/Intel runtime detection, PyTorch/inference-runtime detection,
capability modeling, and deterministic planning. No Apply mechanism
exists — see docs/ai/architecture.md."""

from __future__ import annotations

from serein.ai.models import AI_CAPABILITIES_SCHEMA_VERSION, AI_PLAN_SCHEMA_VERSION, AIPlan
from serein.ai.planner import build_ai_plan

__all__ = [
    "AI_CAPABILITIES_SCHEMA_VERSION",
    "AI_PLAN_SCHEMA_VERSION",
    "AIPlan",
    "build_ai_plan",
]
