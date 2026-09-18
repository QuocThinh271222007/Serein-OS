"""The eleven-step provisioning sequence (Section 8).

Every step is a plain function ``(FirstbootContext) -> StepOutcome`` -
this is the "injectable step-runner/callback" DI point Section 38 asks
for, mirroring ``serein.development.runner``'s injectable
``CommandRunner``: production code runs :data:`DEFAULT_STEPS` unchanged;
tests build their own ``tuple[StepDefinition, ...]`` with one step's
``func`` swapped for a fake that fails deterministically, rather than
adding a production-only "fail here" debug flag to the engine itself.

Each step calls the real, existing S1-S6.5 read-only ``status``
detectors (never reimplementing detection) and, where genuinely
justified, writes a narrowly-scoped registration file recording what was
*honestly observed* - never a fabricated "installed"/"active" claim.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from serein.ai.status import build_ai_status
from serein.cyber.status import build_cyber_status
from serein.desktop import config as desktop_config
from serein.desktop.models import DESKTOP_CONFIG_VERSION
from serein.desktop.status import build_desktop_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.status import build_development_status
from serein.distribution.pathsafety import resolve_within
from serein.hardware.executor import apply_hardware_plan
from serein.hardware.planner import build_hardware_plan
from serein.hardware.probe import probe_hardware
from serein.installer.payload import InstallStateMarker
from serein.veil.status import build_veil_status

from .atomic import atomic_write_json, atomic_write_text
from .eligibility import evaluate_eligibility
from .installstate import install_state_path, read_install_state
from .livemedia import detect_live_media
from .models import (
    AETHER_REGISTRATION_RELATIVE_PATH,
    FOCUS_DEFAULT_RELATIVE_PATH,
    FORGE_REGISTRATION_RELATIVE_PATH,
    HARDWARE_SNAPSHOT_RELATIVE_PATH,
    VEIL_REGISTRATION_RELATIVE_PATH,
    WARD_REGISTRATION_RELATIVE_PATH,
)

#: Section 21: the repository-defined default focus target (see
#: ``serein.focus.models.FOCUS_TARGETS`` / ``FocusStatusReport.policy_baseline``
#: - "balanced" means "no professional domain owns primary-focus
#: preference", the correct, safe, un-opinionated default for a freshly
#: provisioned system). FOCUS_APPLY stays False - this is a *default
#: label* recorded for future consumers, never a cgroup/scheduler
#: mutation (S6.5/ADR-0026 remains planning-only).
DEFAULT_FOCUS_BASELINE = "balanced"

#: Section 22: the one service S7.2 itself is responsible for. No other
#: service is enabled by first-boot provisioning - see
#: ``step_system_services`` and ``docs/firstboot/architecture.md``.
FIRSTBOOT_SERVICE_NAME = "serein-firstboot.service"


@dataclass(frozen=True)
class StepOutcome:
    passed: bool
    detail: str
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class FirstbootContext:
    """Read-only inputs shared by every step, plus a mutable
    ``evidence`` accumulator the engine fills in after each step
    completes (so later steps - notably ``10-final-validation`` - can
    inspect what earlier steps actually observed)."""

    root: Path
    runner: CommandRunner
    install_state: InstallStateMarker
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Section 29: the *persisted* per-step status as of the start of
    #: this run, seeded by the engine from ``FirstbootState.steps`` and
    #: updated as each step completes - this is what
    #: ``step_final_validation`` checks, never the transient ``evidence``
    #: dict alone, so a retried run correctly recognizes steps that
    #: passed in an *earlier* invocation and were skipped this time.
    step_statuses: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StepDefinition:
    id: str
    title: str
    func: Callable[[FirstbootContext], StepOutcome]


def _write_registration(ctx: FirstbootContext, relative_path: str, data: dict[str, Any]) -> Path:
    target = resolve_within(ctx.root, relative_path)
    atomic_write_json(target, data)
    return target


def step_validate_installation(ctx: FirstbootContext) -> StepOutcome:
    """01: re-validate the handoff *after* the lock is held (TOCTOU
    protection - Section 26) rather than trusting the pre-lock
    eligibility snapshot the engine used to decide to start at all."""
    live = detect_live_media(ctx.root)
    if live.is_live_media:
        return StepOutcome(
            passed=False,
            detail="live-media evidence observed during validate-installation",
            reason=f"live_media_detected: {'; '.join(live.reasons) or 'unspecified'}",
        )

    result = read_install_state(ctx.root)
    if not result.present or not result.valid:
        return StepOutcome(
            passed=False,
            detail="install-state.json is no longer present/valid",
            reason=result.error or "install_state_unavailable",
        )

    marker = result.marker
    assert marker is not None
    if marker.source_commit != ctx.install_state.source_commit or (
        marker.firstboot_provisioning != ctx.install_state.firstboot_provisioning
    ):
        return StepOutcome(
            passed=False,
            detail="install-state.json changed between eligibility check and lock acquisition",
            reason="install_state_changed_during_run",
        )

    return StepOutcome(
        passed=True,
        detail="install-state.json re-validated under lock",
        evidence={"install_state": marker.to_dict()},
    )


#: Section 14: the canonical Serein directories - never invented paths.
_CORE_DIRECTORIES: tuple[str, ...] = (
    "etc/serein",
    "var/lib/serein",
    "var/lib/serein/firstboot",
    "var/log/serein",
)


def step_initialize_directories(ctx: FirstbootContext) -> StepOutcome:
    """02: create the canonical Serein directories with sane, narrow
    permissions (Section 14, 26 - "No world-writable state. No broad
    chmod."). Each directory is created/chmod'd individually - never a
    recursive chmod over an existing tree."""
    created = []
    for relative in _CORE_DIRECTORIES:
        target = resolve_within(ctx.root, relative)
        target.mkdir(parents=True, exist_ok=True)
        try:
            target.chmod(0o755)
        except OSError:
            # Best-effort: this dev environment (Windows) and some test
            # fixtures do not support POSIX chmod semantics; the real
            # target (Ubuntu/systemd, root) always does.
            pass
        created.append(str(target))

    return StepOutcome(
        passed=True,
        detail=f"ensured {len(created)} canonical Serein directories exist (mode 0755)",
        evidence={"directories": created, "mode": "0755"},
    )


def step_apply_core_config(ctx: FirstbootContext) -> StepOutcome:
    """03: hardware-aware initial state (Section 16), a real but narrow
    S2 hardware apply pass (SAFE_WITH_CAPABILITY_CHECK - Phase-7-
    completion Section 8/25; see ``serein.hardware.executor``), and the
    default Focus baseline label (Section 21 - planning/awareness only,
    never a cgroup/scheduler mutation - ADR-0026 remains untouched by
    this step).

    Hardware actions are applied against the repository-defined
    ``"balanced"`` profile - the same neutral default
    ``DEFAULT_FOCUS_BASELINE`` already uses, correct for a freshly
    provisioned system with no active workspace opinion yet. An
    individual hardware action failing (e.g. no power-profiles-daemon
    on this host) never fails this step or the overall run - hardware
    tuning is optional polish, never a release-blocking concern
    (Section 89) - the per-action outcome is still recorded in full,
    never silently dropped.
    """
    hw = probe_hardware(ctx.root)
    snapshot = {
        "cpu_vendor": hw.cpu.vendor,
        "cpu_model": hw.cpu.model_name,
        "logical_cores": hw.cpu.logical_cores,
        "physical_cores": hw.cpu.physical_cores,
        "memory_total_bytes": hw.memory.total_bytes,
        "gpu_count": len(hw.gpu),
        "gpu_summary": [f"{g.vendor or 'unknown'} ({g.kind or 'unknown'})" for g in hw.gpu],
        "storage_device_count": len(hw.storage),
        "virtualization": hw.environment.virtualization,
    }
    _write_registration(ctx, HARDWARE_SNAPSHOT_RELATIVE_PATH, snapshot)

    hardware_plan = build_hardware_plan(DEFAULT_FOCUS_BASELINE, ctx.root)
    action_results = apply_hardware_plan(hardware_plan, ctx.root, ctx.runner)

    focus_default = {
        "policy_baseline": DEFAULT_FOCUS_BASELINE,
        "runtime_enforcement": False,
        "applied": False,
        "note": "planning-only default label (ADR-0026) - no cgroup/scheduler mutation performed",
    }
    _write_registration(ctx, FOCUS_DEFAULT_RELATIVE_PATH, focus_default)

    return StepOutcome(
        passed=True,
        detail=(
            "wrote hardware snapshot, applied S2 hardware plan "
            f"({len(action_results)} actions), and default Focus baseline"
        ),
        evidence={
            "hardware_snapshot": snapshot,
            "hardware_actions": [r.to_dict() for r in action_results],
            "focus_default": focus_default,
        },
    )


def step_desktop_baseline(ctx: FirstbootContext) -> StepOutcome:
    """04: S1 desktop system-defaults verification + config-version
    record (SAFE_AUTOMATIC - Phase-7-completion Section 8).

    Staging the actual system-owned resource files
    (``desktop.config.RESOURCES``, ``owner="system"``) onto the
    installed target's real filesystem paths (``/etc/xdg/kdeglobals``,
    etc.) is a package/install-time concern, not a first-boot concern -
    the idiomatic Linux-native place for "install this file to this
    system path" is a package's own file manifest (a future
    ``serein-desktop`` .deb, or curtin late-commands during install),
    never a first-boot runtime copy (Section 22/72 - "few permanently
    resident services... prefer Linux-native mechanisms"). This step's
    own job is narrower and correctly scoped: VERIFY every
    system-owned resource actually landed where it should (never
    re-derive that list - the same ``desktop.config.RESOURCES``
    contract ``desktop.plan``/``desktop.doctor`` already use), then
    RECORD the Serein desktop config-version marker once verification
    passes - the one real mutation this step performs, and the exact
    fact ``desktop.detect.detect_config_state`` already knows how to
    read back (this step's "verify" reuses that SAME existing
    detector after writing the marker, rather than inventing a second,
    possibly-diverging way to answer "did the desktop preset apply").
    Never touches an ``owner="first-login-user"`` resource (the
    Look-and-Feel package) - there is no user session inside a
    oneshot boot unit, and Section 10 requires never overwriting user
    config after first boot.

    Tracked gap (not silently glossed over): staging these files onto
    the installed target is not yet implemented anywhere in the
    build/install pipeline - see docs/firstboot/known-limitations.md
    (SEREIN-DESKTOP-STAGING-PENDING). Until that exists, this step
    legitimately fails closed on a real system rather than falsely
    reporting success.
    """
    system_resources = [r for r in desktop_config.RESOURCES if r.owner == "system"]
    missing = [
        r for r in system_resources
        if not resolve_within(ctx.root, r.target_path.lstrip("/")).is_file()
    ]
    if missing:
        return StepOutcome(
            passed=False,
            detail=(
                f"{len(missing)} of {len(system_resources)} system-owned desktop "
                "resources are not staged at their target path (staging happens at "
                "package/install time, not first-boot - see "
                "SEREIN-DESKTOP-STAGING-PENDING)"
            ),
            reason="desktop_resources_not_staged",
            evidence={"missing_target_paths": [r.target_path for r in missing]},
        )

    version_path = resolve_within(ctx.root, "etc/serein/desktop/config-version")
    atomic_write_text(version_path, f"{DESKTOP_CONFIG_VERSION}\n")

    status = build_desktop_status(root=ctx.root, env={})
    if (
        not status.config.serein_preset_applied
        or status.config.desktop_config_version != DESKTOP_CONFIG_VERSION
    ):
        return StepOutcome(
            passed=False,
            detail="wrote desktop config-version marker but verification did not observe it",
            reason="desktop_config_verify_failed",
            evidence={
                "serein_preset_applied": status.config.serein_preset_applied,
                "desktop_config_version": status.config.desktop_config_version,
            },
        )

    return StepOutcome(
        passed=True,
        detail=(
            f"verified {len(system_resources)} system-owned desktop resources present; "
            f"recorded config-version={DESKTOP_CONFIG_VERSION}"
        ),
        evidence={"desktop_baseline": {
            "verified_target_paths": [r.target_path for r in system_resources],
            "config_version": DESKTOP_CONFIG_VERSION,
            "applied_by_firstboot": False,
            "note": (
                "firstboot verifies+records only; staging the files themselves is a "
                "package/install-time concern (SEREIN-DESKTOP-STAGING-PENDING)"
            ),
        }},
    )


def step_development_registration(ctx: FirstbootContext) -> StepOutcome:
    """05: Forge (S3) - detect/verify/register only, never reinstall."""
    status = build_development_status(runner=ctx.runner, home=None)
    record = dataclasses.asdict(status)
    _write_registration(ctx, FORGE_REGISTRATION_RELATIVE_PATH, record)
    return StepOutcome(
        passed=True,
        detail="registered development (Forge) toolchain status",
        evidence={"forge_registration": record},
    )


def step_ai_registration(ctx: FirstbootContext) -> StepOutcome:
    """06: Aether (S4) - metadata/state only. No model download, no GPU
    workload activation, no permanent inference daemon start
    (AI_MODEL_DOWNLOAD_COUNT=0)."""
    status = build_ai_status(root=ctx.root, runner=ctx.runner)
    record = dataclasses.asdict(status)
    _write_registration(ctx, AETHER_REGISTRATION_RELATIVE_PATH, record)
    return StepOutcome(
        passed=True,
        detail="registered AI (Aether) backend/runtime readiness state",
        evidence={"aether_registration": record},
    )


def step_cyber_registration(ctx: FirstbootContext) -> StepOutcome:
    """07: Ward (S5) - capability/state registration only. No network
    scan, no sniffer, no offensive session (AUTO_CYBER_EXECUTION=false).
    ``build_cyber_status`` itself only ever runs read-only
    ``--version``/``--help``-style probes (see
    ``serein.development.runner`` docstring)."""
    status = build_cyber_status(root=ctx.root, runner=ctx.runner)
    record = dataclasses.asdict(status)
    _write_registration(ctx, WARD_REGISTRATION_RELATIVE_PATH, record)
    return StepOutcome(
        passed=True,
        detail="registered cyber (Ward) capability state",
        evidence={"ward_registration": record},
    )


def step_privacy_registration(ctx: FirstbootContext) -> StepOutcome:
    """08: Veil (S6) - configuration-state registration only.
    GLOBAL_TOR_ENABLEMENT stays false; Tor/Whonix are never started
    (ADR-0021/0024)."""
    status = build_veil_status(root=ctx.root, runner=ctx.runner, home=None)
    record = dataclasses.asdict(status)
    _write_registration(ctx, VEIL_REGISTRATION_RELATIVE_PATH, record)
    return StepOutcome(
        passed=True,
        detail="registered Veil privacy-workspace configuration state",
        evidence={"veil_registration": record},
    )


def step_system_services(ctx: FirstbootContext) -> StepOutcome:
    """09: services policy (Section 22). Only ``serein-firstboot.service``
    itself is enabled by first-boot provisioning - no optional subsystem
    daemon is enabled merely because it exists (lazy/on-demand is
    preferred everywhere S1-S6.5 already establishes)."""
    systemctl_probe = ctx.runner.run(["systemctl", "--version"])
    systemctl_available = systemctl_probe is not None and systemctl_probe.returncode == 0

    services = [
        {
            "service": FIRSTBOOT_SERVICE_NAME,
            "why": "runs this first-boot provisioning sequence exactly once at boot",
            "enabled_by_default": True,
            "security_impact": (
                "low - oneshot root unit, single bounded execution per boot, "
                "no persistent daemon, self-limiting via S7.2's own idempotency state"
            ),
            "resource_impact": "negligible - bounded run, exits promptly once complete",
        },
    ]
    return StepOutcome(
        passed=True,
        detail=f"documented services policy (systemctl available: {systemctl_available})",
        evidence={"services": services, "systemctl_available": systemctl_available},
    )


def step_final_validation(ctx: FirstbootContext) -> StepOutcome:
    """10: confirm every prior step actually left real evidence behind,
    and that the handoff still reads exactly as this run expects (it is
    not yet flipped to "complete" - that is step 11's job alone)."""
    required_prior = (
        "01-validate-installation",
        "02-initialize-directories",
        "03-apply-core-config",
        "04-desktop-baseline",
        "05-development-registration",
        "06-ai-registration",
        "07-cyber-registration",
        "08-privacy-registration",
        "09-system-services",
    )
    not_passed = [
        step_id for step_id in required_prior if ctx.step_statuses.get(step_id) != "passed"
    ]
    if not_passed:
        return StepOutcome(
            passed=False,
            detail="one or more prior steps are not recorded as passed",
            reason=f"steps_not_passed: {not_passed}",
        )

    result = read_install_state(ctx.root)
    if not result.valid or result.marker is None:
        return StepOutcome(
            passed=False,
            detail="install-state.json is not valid at final validation",
            reason=result.error or "install_state_unavailable",
        )
    if result.marker.firstboot_provisioning != "pending":
        return StepOutcome(
            passed=False,
            detail="install-state.json firstboot_provisioning changed unexpectedly "
                   "before mark-complete",
            reason=f"unexpected_firstboot_provisioning: {result.marker.firstboot_provisioning!r}",
        )

    for relative in _CORE_DIRECTORIES:
        if not resolve_within(ctx.root, relative).is_dir():
            return StepOutcome(
                passed=False,
                detail=f"expected directory missing: {relative}",
                reason=f"missing_directory: {relative}",
            )

    return StepOutcome(
        passed=True,
        detail="all prior steps left real evidence; handoff still consistent",
        evidence={"validated_steps": list(required_prior)},
    )


def step_mark_complete(ctx: FirstbootContext) -> StepOutcome:
    """11: the one, single mutation to ``/etc/serein/install-state.json``
    - flips ``firstboot_provisioning`` to ``"complete"`` while preserving
    every other field verbatim (Section 30 - never destroy S7.1's audit
    evidence)."""
    result = read_install_state(ctx.root)
    if not result.valid or result.marker is None:
        return StepOutcome(
            passed=False,
            detail="cannot mark complete: install-state.json is not valid",
            reason=result.error or "install_state_unavailable",
        )

    final_marker = dataclasses.replace(result.marker, firstboot_provisioning="complete")
    atomic_write_json(install_state_path(ctx.root), final_marker.to_dict())

    return StepOutcome(
        passed=True,
        detail="install-state.json firstboot_provisioning flipped to 'complete'",
        evidence={"install_state_final": final_marker.to_dict()},
    )


DEFAULT_STEPS: tuple[StepDefinition, ...] = (
    StepDefinition(
        "01-validate-installation", "Validate installation handoff", step_validate_installation
    ),
    StepDefinition(
        "02-initialize-directories", "Initialize canonical directories",
        step_initialize_directories,
    ),
    StepDefinition(
        "03-apply-core-config", "Apply core config (hardware + focus default)",
        step_apply_core_config,
    ),
    StepDefinition(
        "04-desktop-baseline", "Register desktop baseline state", step_desktop_baseline
    ),
    StepDefinition(
        "05-development-registration", "Register development (Forge) state",
        step_development_registration,
    ),
    StepDefinition("06-ai-registration", "Register AI (Aether) state", step_ai_registration),
    StepDefinition(
        "07-cyber-registration", "Register cyber (Ward) state", step_cyber_registration
    ),
    StepDefinition(
        "08-privacy-registration", "Register privacy (Veil) state", step_privacy_registration
    ),
    StepDefinition("09-system-services", "Document services policy", step_system_services),
    StepDefinition("10-final-validation", "Final validation", step_final_validation),
    StepDefinition("11-mark-complete", "Mark provisioning complete", step_mark_complete),
)


def build_context(
    root: Path, install_state: InstallStateMarker, runner: CommandRunner = DEFAULT_RUNNER
) -> FirstbootContext:
    return FirstbootContext(root=root, runner=runner, install_state=install_state)


__all__ = [
    "DEFAULT_STEPS",
    "FirstbootContext",
    "StepDefinition",
    "StepOutcome",
    "build_context",
    "evaluate_eligibility",
]
