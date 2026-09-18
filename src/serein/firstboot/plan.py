"""``serein firstboot plan``: a side-effect-free preview (Section 13).

Shows exactly what a real ``run_firstboot`` would change - directories,
config files, systemd unit, desktop defaults, Serein component
registrations, state files - without probing any subsystem detector or
writing anything. Purely static, deterministic descriptions of
:data:`serein.firstboot.steps.DEFAULT_STEPS`, plus the one genuinely
dynamic (but still read-only) fact: current eligibility.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT

from .eligibility import evaluate_eligibility
from .models import (
    AETHER_REGISTRATION_RELATIVE_PATH,
    FIRSTBOOT_PLAN_SCHEMA_VERSION,
    FOCUS_DEFAULT_RELATIVE_PATH,
    FORGE_REGISTRATION_RELATIVE_PATH,
    HARDWARE_SNAPSHOT_RELATIVE_PATH,
    INSTALL_STATE_RELATIVE_PATH,
    VEIL_REGISTRATION_RELATIVE_PATH,
    WARD_REGISTRATION_RELATIVE_PATH,
    FirstbootPlanReport,
    FirstbootPlanStep,
)
from .steps import FIRSTBOOT_SERVICE_NAME

_PLAN_STEPS: tuple[FirstbootPlanStep, ...] = (
    FirstbootPlanStep(
        "01-validate-installation", "Validate installation handoff",
        (INSTALL_STATE_RELATIVE_PATH,),
        "Re-reads and re-validates /etc/serein/install-state.json under the provisioning lock.",
    ),
    FirstbootPlanStep(
        "02-initialize-directories", "Initialize canonical directories",
        ("etc/serein", "var/lib/serein", "var/lib/serein/firstboot", "var/log/serein"),
        "Creates the canonical Serein directories (mode 0755) if not already present.",
    ),
    FirstbootPlanStep(
        "03-apply-core-config", "Apply core config",
        (HARDWARE_SNAPSHOT_RELATIVE_PATH, FOCUS_DEFAULT_RELATIVE_PATH),
        "Writes a hardware capability snapshot (S2) and the default Focus baseline label "
        "('balanced', planning-only, ADR-0026).",
    ),
    FirstbootPlanStep(
        "04-desktop-baseline", "Register desktop baseline",
        (),
        "Registers observed desktop status (S1) - no unattended apply mechanism exists yet, "
        "so this is a registration/no-op, never a desktop mutation.",
    ),
    FirstbootPlanStep(
        "05-development-registration", "Register development (Forge) state",
        (FORGE_REGISTRATION_RELATIVE_PATH,),
        "Detects and registers Forge toolchain state (S3) - never installs/reinstalls anything.",
    ),
    FirstbootPlanStep(
        "06-ai-registration", "Register AI (Aether) state",
        (AETHER_REGISTRATION_RELATIVE_PATH,),
        "Detects and registers AI backend/runtime readiness (S4) - no model download "
        "(AI_MODEL_DOWNLOAD_COUNT=0), no GPU workload activation.",
    ),
    FirstbootPlanStep(
        "07-cyber-registration", "Register cyber (Ward) state",
        (WARD_REGISTRATION_RELATIVE_PATH,),
        "Detects and registers cyber capability state (S5) - no scan, no sniffer, no offensive "
        "session (AUTO_CYBER_EXECUTION=false).",
    ),
    FirstbootPlanStep(
        "08-privacy-registration", "Register privacy (Veil) state",
        (VEIL_REGISTRATION_RELATIVE_PATH,),
        "Detects and registers Veil configuration state (S6) - Tor/Whonix stay opt-in "
        "(GLOBAL_TOR_ENABLEMENT=false).",
    ),
    FirstbootPlanStep(
        "09-system-services", "Document services policy",
        (),
        f"Documents the services policy - only {FIRSTBOOT_SERVICE_NAME} itself is enabled by "
        "default; no optional subsystem service is enabled merely because it exists.",
    ),
    FirstbootPlanStep(
        "10-final-validation", "Final validation",
        (),
        "Verifies every prior step left real evidence and the handoff is still consistent.",
    ),
    FirstbootPlanStep(
        "11-mark-complete", "Mark provisioning complete",
        (INSTALL_STATE_RELATIVE_PATH,),
        "Flips install-state.json's firstboot_provisioning to 'complete', preserving every "
        "other field verbatim.",
    ),
)


def build_firstboot_plan(root: Path = DEFAULT_ROOT) -> FirstbootPlanReport:
    eligibility = evaluate_eligibility(root)
    return FirstbootPlanReport(
        schema_version=FIRSTBOOT_PLAN_SCHEMA_VERSION,
        eligibility_status=eligibility.status,
        eligibility_reason=eligibility.reason,
        steps=_PLAN_STEPS,
        systemd_unit=FIRSTBOOT_SERVICE_NAME,
        mutation="none",
    )
