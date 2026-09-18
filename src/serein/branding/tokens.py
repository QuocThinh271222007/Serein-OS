"""Serein design tokens loader (S7.2 Section 6, 'Quiet Velocity').

``branding/tokens/design-tokens.json`` is the single canonical source
of Serein's visual identity - every consumer (GRUB/Plymouth theme
generation, desktop color-scheme files, Fastfetch/terminal output,
docs) reads through this module rather than hardcoding a literal
value. Mirrors ``schemas/design-tokens.schema.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
DESIGN_TOKENS_PATH = _REPO_ROOT / "branding" / "tokens" / "design-tokens.json"


@dataclass(frozen=True)
class ColorToken:
    name: str
    hex: str
    role: str


@dataclass(frozen=True)
class VisualRatio:
    neutral: float
    accent: float
    focus_status: float


@dataclass(frozen=True)
class MotionBudget:
    animation_duration_ms_min: int
    animation_duration_ms_max: int
    reduced_motion_supported: bool


@dataclass(frozen=True)
class DesignTokens:
    schema_version: int
    design_language: str
    core_values: tuple[str, ...]
    colors: tuple[ColorToken, ...]
    visual_ratio: VisualRatio
    motion: MotionBudget

    def color(self, name: str) -> ColorToken:
        for token in self.colors:
            if token.name == name:
                return token
        raise KeyError(f"no design token named {name!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "design_language": self.design_language,
            "core_values": list(self.core_values),
            "colors": {t.name: {"hex": t.hex, "role": t.role} for t in self.colors},
            "visual_ratio": {
                "neutral": self.visual_ratio.neutral,
                "accent": self.visual_ratio.accent,
                "focus_status": self.visual_ratio.focus_status,
            },
            "motion": {
                "animation_duration_ms_min": self.motion.animation_duration_ms_min,
                "animation_duration_ms_max": self.motion.animation_duration_ms_max,
                "reduced_motion_supported": self.motion.reduced_motion_supported,
            },
        }


def load_design_tokens(path: Path = DESIGN_TOKENS_PATH) -> DesignTokens:
    data = json.loads(path.read_text(encoding="utf-8"))
    colors = tuple(
        ColorToken(name=name, hex=value["hex"], role=value["role"])
        for name, value in data["colors"].items()
    )
    return DesignTokens(
        schema_version=data["schema_version"],
        design_language=data["design_language"],
        core_values=tuple(data["core_values"]),
        colors=colors,
        visual_ratio=VisualRatio(**data["visual_ratio"]),
        motion=MotionBudget(**data["motion"]),
    )
