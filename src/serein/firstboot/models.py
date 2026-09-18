"""Structured representations for the First-Boot Provisioning subsystem
(S7.2). Mirrors the pattern S1-S7.1 established - dataclasses only, no
behavior. See ``docs/firstboot/architecture.md``.

Path layout (Section 30 of the S7.2 brief - "could use install-state.json
+ a separate firstboot state file with clear responsibility"):

- ``/etc/serein/install-state.json`` - S7.1's installation-provenance
  marker (``serein.installer.payload.InstallStateMarker``). S7.2 only
  ever mutates its ``firstboot_provisioning`` field, and only once, in
  the final ``11-mark-complete`` step - every other field (source
  commit, media version, phase, schema version) is preserved verbatim
  so S7.1's own audit evidence is never destroyed.
- ``/var/lib/serein/firstboot/state.json`` - S7.2's own transactional
  step-by-step state machine (this module). The authoritative source
  for "has firstboot already run" from S7.2's own perspective -
  independent of whether the install-state.json flip has landed yet,
  so a crash between the last step passing and that flip cannot cause
  re-provisioning.
- ``/var/lib/serein/firstboot/firstboot-evidence.json`` - the
  machine-readable evidence record for one provisioning attempt
  (Section 31).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FIRSTBOOT_STATE_SCHEMA_VERSION = 1
FIRSTBOOT_EVIDENCE_SCHEMA_VERSION = 1
FIRSTBOOT_STATUS_SCHEMA_VERSION = 1
FIRSTBOOT_PLAN_SCHEMA_VERSION = 1

#: Paths are always expressed relative to an injectable root (Section 25/26
#: - tests substitute a fixture directory; production uses "/").
INSTALL_STATE_RELATIVE_PATH = "etc/serein/install-state.json"
FIRSTBOOT_DIR_RELATIVE_PATH = "var/lib/serein/firstboot"
FIRSTBOOT_STATE_RELATIVE_PATH = "var/lib/serein/firstboot/state.json"
FIRSTBOOT_EVIDENCE_RELATIVE_PATH = "var/lib/serein/firstboot/firstboot-evidence.json"
FIRSTBOOT_LOCK_RELATIVE_PATH = "var/lib/serein/firstboot/firstboot.lock"
HARDWARE_SNAPSHOT_RELATIVE_PATH = "var/lib/serein/firstboot/hardware-snapshot.json"
FOCUS_DEFAULT_RELATIVE_PATH = "var/lib/serein/firstboot/focus-default.json"
FORGE_REGISTRATION_RELATIVE_PATH = "var/lib/serein/firstboot/forge-registration.json"
AETHER_REGISTRATION_RELATIVE_PATH = "var/lib/serein/firstboot/aether-registration.json"
WARD_REGISTRATION_RELATIVE_PATH = "var/lib/serein/firstboot/ward-registration.json"
VEIL_REGISTRATION_RELATIVE_PATH = "var/lib/serein/firstboot/veil-registration.json"
SEREIN_LOG_DIR_RELATIVE_PATH = "var/log/serein"

#: Section 7: the required high-level state machine. "repair_required" is
#: deliberately not modeled (Section 7 - "Optional... if strongly
#: justified") - S7.2 has no repair mechanism, so a state it could never
#: transition out of would be dishonest; unrecoverable failure is simply
#: "failed" with durable evidence for a future S7.3 to consume.
FIRSTBOOT_STATES: tuple[str, ...] = ("pending", "running", "failed", "complete")

#: Section 8: per-step lifecycle status.
STEP_STATUSES: tuple[str, ...] = ("pending", "running", "passed", "failed", "skipped")

#: Section 8-9: the canonical, ordered step sequence. Every persisted
#: FirstbootState always carries exactly these ids in this order -
#: reconciled by ``serein.firstboot.statefile`` if an older state file
#: predates a step-list change.
STEP_IDS: tuple[str, ...] = (
    "01-validate-installation",
    "02-initialize-directories",
    "03-apply-core-config",
    "04-desktop-baseline",
    "05-development-registration",
    "06-ai-registration",
    "07-cyber-registration",
    "08-privacy-registration",
    "09-system-services",
    "10-final-validation",
    "11-mark-complete",
)

#: Section 5: the read-only eligibility verdict.
ELIGIBILITY_STATUSES: tuple[str, ...] = ("ELIGIBLE", "BLOCKED", "NOT_REQUIRED")


@dataclass(frozen=True)
class StepRecord:
    """One step's lifecycle evidence (Section 8) - deliberately more than
    a single boolean, so a partial run leaves real step-level evidence
    behind rather than one fragile flag written only at the end."""

    id: str
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STEP_STATUSES:
            raise ValueError(f"status={self.status!r} must be one of {STEP_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StepRecord:
        return StepRecord(
            id=data["id"],
            status=data.get("status", "pending"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            failure_reason=data.get("failure_reason"),
        )


@dataclass
class FirstbootState:
    """S7.2's own transactional state machine (Section 6-9). Mutable -
    the engine updates it in place, checkpointing via
    ``serein.firstboot.statefile.FirstbootStateStore`` after every single
    step transition (Section 8 - "do not use a single fragile boolean
    written only at the end without step-level evidence")."""

    schema_version: int = FIRSTBOOT_STATE_SCHEMA_VERSION
    state: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None
    steps: list[StepRecord] = field(default_factory=list)
    #: Section 9: "first failure wins" - set once, by
    #: ``serein.firstboot.engine._record_first_failure``, and never
    #: overwritten by a later, unrelated failure while it is still set.
    #: Cleared only when the recorded stage itself is retried and passes
    #: (Section 29 - stale failure evidence must not outlive its cause).
    first_failure_stage: str | None = None
    first_failure_reason: str | None = None
    source_commit: str | None = None

    def __post_init__(self) -> None:
        if self.state not in FIRSTBOOT_STATES:
            raise ValueError(f"state={self.state!r} must be one of {FIRSTBOOT_STATES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "updated_at": self.updated_at,
            "steps": [s.to_dict() for s in self.steps],
            "first_failure_stage": self.first_failure_stage,
            "first_failure_reason": self.first_failure_reason,
            "source_commit": self.source_commit,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> FirstbootState:
        return FirstbootState(
            schema_version=data.get("schema_version", FIRSTBOOT_STATE_SCHEMA_VERSION),
            state=data.get("state", "pending"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            updated_at=data.get("updated_at"),
            steps=[StepRecord.from_dict(s) for s in data.get("steps", [])],
            first_failure_stage=data.get("first_failure_stage"),
            first_failure_reason=data.get("first_failure_reason"),
            source_commit=data.get("source_commit"),
        )


@dataclass(frozen=True)
class LiveMediaEvidence:
    """Section 10: live-media detection must never rely on a single
    heuristic. Every field is an independent, honestly-observed signal;
    ``is_live_media`` is the combined verdict, never fabricated from
    absence of evidence (an unreadable/missing probe file just means
    that particular signal is ``False``, not "unknown-therefore-live")."""

    is_live_media: bool
    reasons: tuple[str, ...] = ()
    casper_conf_present: bool = False
    live_run_dir_present: bool = False
    cmdline_indicates_live: bool = False
    overlay_root_fs: bool = False
    cdrom_dir_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass(frozen=True)
class InstallStateReadResult:
    """Result of reading/validating ``/etc/serein/install-state.json``
    (Section 5). ``marker`` is only ever populated when ``valid`` is
    True - callers must never branch on ``marker is not None`` without
    also checking ``valid`` first."""

    present: bool
    valid: bool
    marker: Any | None  # serein.installer.payload.InstallStateMarker | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "valid": self.valid,
            "marker": self.marker.to_dict() if self.marker is not None else None,
            "error": self.error,
        }


@dataclass(frozen=True)
class EligibilityResult:
    """Section 5: "valid install-state + installation_complete=true +
    firstboot_provisioning=pending -> provisioning eligible. Otherwise:
    PROVISIONING=BLOCKED or PROVISIONING=NOT_REQUIRED depending on
    state." Side-effect free - only ever reads files, never writes."""

    status: str
    reason: str
    install_state: InstallStateReadResult
    live_media: LiveMediaEvidence

    def __post_init__(self) -> None:
        if self.status not in ELIGIBILITY_STATUSES:
            raise ValueError(f"status={self.status!r} must be one of {ELIGIBILITY_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "install_state": self.install_state.to_dict(),
            "live_media": self.live_media.to_dict(),
        }


@dataclass(frozen=True)
class FirstbootEvidence:
    """Machine-readable provisioning evidence (Section 31). Never
    includes a secret, credential, username, or real hostname - every
    embedded subsystem status report already carries that same
    discipline from S1-S6.5 (Section 24)."""

    schema_version: int
    source_commit: str | None
    install_state_valid: bool
    started_at: str | None
    completed_at: str | None
    steps: tuple[dict[str, Any], ...]
    first_failure_stage: str | None
    first_failure_reason: str | None
    desktop_baseline: dict[str, Any] | None
    hardware_snapshot: dict[str, Any] | None
    hardware_actions: list[dict[str, Any]] | None
    forge_registration: dict[str, Any] | None
    aether_registration: dict[str, Any] | None
    ward_registration: dict[str, Any] | None
    veil_registration: dict[str, Any] | None
    focus_default: dict[str, Any] | None
    network_required: bool
    network_available: bool | None
    final_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "install_state_valid": self.install_state_valid,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "steps": list(self.steps),
            "first_failure_stage": self.first_failure_stage,
            "first_failure_reason": self.first_failure_reason,
            "desktop_baseline": self.desktop_baseline,
            "hardware_snapshot": self.hardware_snapshot,
            "hardware_actions": self.hardware_actions,
            "forge_registration": self.forge_registration,
            "aether_registration": self.aether_registration,
            "ward_registration": self.ward_registration,
            "veil_registration": self.veil_registration,
            "focus_default": self.focus_default,
            "network_required": self.network_required,
            "network_available": self.network_available,
            "final_status": self.final_status,
        }


@dataclass(frozen=True)
class FirstbootStatusReport:
    """``serein firstboot status`` output - read-only (Section 12)."""

    schema_version: int
    eligibility_status: str
    eligibility_reason: str
    install_state_present: bool
    install_state_valid: bool
    firstboot_provisioning: str | None
    state: str
    steps_summary: dict[str, int]
    first_failure_stage: str | None
    first_failure_reason: str | None
    live_media_detected: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FirstbootPlanStep:
    id: str
    title: str
    would_create: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["would_create"] = list(self.would_create)
        return data


@dataclass(frozen=True)
class FirstbootPlanReport:
    """``serein firstboot plan`` output (Section 13) - side-effect free;
    shows exactly what a real run would change without changing
    anything."""

    schema_version: int
    eligibility_status: str
    eligibility_reason: str
    steps: tuple[FirstbootPlanStep, ...]
    systemd_unit: str
    mutation: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "eligibility_status": self.eligibility_status,
            "eligibility_reason": self.eligibility_reason,
            "steps": [s.to_dict() for s in self.steps],
            "systemd_unit": self.systemd_unit,
            "mutation": self.mutation,
        }
