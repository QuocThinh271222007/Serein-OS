"""``serein focus plan <target>``: deterministic, evidence-based focus
planning. No Apply mechanism exists (Section 3-4) - this module only
ever reads already-gathered S2-S6 evidence and returns the canonical
``FocusPolicy`` (Section 88 - the plan output *is* the policy, never a
second, independently-derived representation).
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.focus.evidence import gather_focus_evidence
from serein.focus.models import FOCUS_TARGETS, FocusPolicy
from serein.focus.policy import build_focus_policy
from serein.hardware._util import DEFAULT_ROOT

VALID_TARGETS: tuple[str, ...] = FOCUS_TARGETS


def build_focus_plan(
    target: str,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
    home: Path | None = None,
) -> FocusPolicy:
    if target not in FOCUS_TARGETS:
        raise ValueError(f"unknown focus target: {target!r}")
    evidence = gather_focus_evidence(root=root, runner=runner, home=home)
    return build_focus_policy(target, evidence)
