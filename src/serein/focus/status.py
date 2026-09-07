"""``serein focus status``: a read-only summary that never fabricates
an applied focus (Section 16-17) - S6.5 has no Apply engine and no
persistence, so ``applied_focus`` is always ``None`` and ``mode`` is
always ``"planning_only"``.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.focus.evidence import gather_focus_evidence
from serein.focus.models import FOCUS_DOMAINS, FOCUS_TARGETS, FocusStatusReport
from serein.focus.policy import evaluate_domain_readiness
from serein.hardware._util import DEFAULT_ROOT


def build_focus_status(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> FocusStatusReport:
    evidence = gather_focus_evidence(root=root, runner=runner, home=home)
    readiness = evaluate_domain_readiness(evidence)
    domain_readiness = {domain: readiness[domain][0] for domain in FOCUS_DOMAINS}

    return FocusStatusReport(
        schema_version=1,
        mode="planning_only",
        runtime_enforcement=False,
        applied_focus=None,
        requested_focus=None,
        policy_baseline="balanced",
        supported_targets=list(FOCUS_TARGETS),
        domain_readiness=domain_readiness,
    )
