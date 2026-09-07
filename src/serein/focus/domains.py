"""Focus target/domain validation and the canonical transition graph.

Plain data and pure validation helpers only - no evidence gathering, no
policy computation (that is ``policy.py``/``transition.py``). See
``docs/focus/domain-model.md``.
"""

from __future__ import annotations

from serein.focus.models import FOCUS_DOMAINS, FOCUS_TARGETS

#: Every canonical, directly-testable transition pair (Section 100) -
#: both directions of every domain pair, plus every domain paired with
#: "balanced". Same-target pairs (``x == x``) are always valid too
#: (Section 57) but are not listed here since they need no graph edge -
#: ``is_valid_transition()`` allows them unconditionally.
CANONICAL_TRANSITIONS: tuple[tuple[str, str], ...] = tuple(
    (a, b)
    for a in FOCUS_TARGETS
    for b in FOCUS_TARGETS
    if a != b
)


def is_valid_target(target: str) -> bool:
    return target in FOCUS_TARGETS


def is_valid_transition(from_focus: str, to_focus: str) -> bool:
    """Every target-pair (including same-target) is a valid, plannable
    transition (Section 100-101) - Serein never refuses to *plan* a
    transition between two recognized targets, even if the resulting
    plan reports ``BLOCKED`` due to readiness constraints."""
    return is_valid_target(from_focus) and is_valid_target(to_focus)


def other_domains(domain: str) -> tuple[str, ...]:
    return tuple(d for d in FOCUS_DOMAINS if d != domain)
