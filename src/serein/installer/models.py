"""Structured representations for the Installer subsystem (S7.1).

Mirrors the pattern S2-S7.0 established - dataclasses only, no
behavior, no runtime dependency on any disk/installer tool. See
``docs/installer/architecture.md``.

The governing principle (Section 8 of the S7.1 contract):

    INSTALL_TARGET_DISK must be explicitly selected AND every
    destructive operation must belong to INSTALL_TARGET_DISK -
    otherwise INSTALL=BLOCKED.

Every dataclass here defaults to the SAFE/UNKNOWN side of that
invariant - a :class:`DiskInfo` starts ``protected=True`` and
``target_eligible=False`` by construction; a caller must explicitly
prove eligibility (``serein.installer.diskguard``), never the reverse.
Absent real evidence, every field is ``None``/empty/``False``, never a
fabricated value (Section 10 - "do not fabricate unavailable values").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

INSTALLER_DISK_INVENTORY_SCHEMA_VERSION = 1
INSTALLER_PLAN_SCHEMA_VERSION = 1
INSTALLER_LAYER_B_EVIDENCE_SCHEMA_VERSION = 1
INSTALL_STATE_SCHEMA_VERSION = 1

#: S7.2 will consume this - S7.1 never advances it past "pending"
#: (Section 27-28: "S7.1 must NOT perform S7.2 provisioning here").
INSTALLER_PHASE = "s7.1"

#: Baseline Serein Alpha target layout (Section 16) - GPT + a ~1 GiB
#: FAT32 ESP + the remaining space as ext4 root. Deliberately no swap,
#: no LVM/RAID/ZFS/encryption/separate-/home in this first baseline.
TARGET_ESP_SIZE_BYTES = 1 * 1024 * 1024 * 1024
TARGET_ESP_FILESYSTEM = "fat32"
TARGET_ROOT_FILESYSTEM = "ext4"

_STAGE_STATUSES = ("pass", "fail", "not_performed")
_IDENTITY_CONFIDENCE_LEVELS = ("low", "medium", "high")
_RESOLUTION_STATUSES = ("resolved", "not_found", "ambiguous", "changed")
_FIRSTBOOT_STATES = ("pending", "complete", "unknown")
_AUTOINSTALL_MODES = ("qa_only", "production")


@dataclass(frozen=True)
class PartitionInfo:
    """One partition observed on a disk - real probe evidence only,
    never fabricated (Section 10)."""

    device_path: str
    kernel_name: str | None = None
    size_bytes: int | None = None
    filesystem: str | None = None
    label: str | None = None
    partition_uuid: str | None = None
    mounted: bool | None = None
    mountpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiskInfo:
    """One whole-disk block device observed by the disk inventory
    (Section 10). ``protected=True``/``target_eligible=False`` are the
    fail-closed defaults - :func:`serein.installer.diskguard.classify_protection`
    is the one place that may ever flip them, and only for the single
    disk a caller explicitly selected."""

    device_path: str
    canonical_path: str | None = None
    kernel_name: str | None = None

    model: str | None = None
    vendor: str | None = None
    serial: str | None = None
    wwn: str | None = None
    id_path: str | None = None

    size_bytes: int | None = None
    logical_sector_size: int | None = None
    physical_sector_size: int | None = None

    transport: str | None = None
    removable: bool | None = None

    partition_table: str | None = None
    partitions: tuple[PartitionInfo, ...] = ()

    filesystem_signatures: tuple[str, ...] = ()

    install_media: bool = False
    mounted: bool = False

    #: Best-effort classification only (Section 13) - never the sole
    #: basis for protection. An unknown/undetectable OS is still
    #: protected, because NON_TARGET == READ_ONLY regardless of what
    #: is on it.
    windows_detected: bool = False
    windows_efi_detected: bool = False
    windows_recovery_detected: bool = False

    protected: bool = True
    protection_reasons: tuple[str, ...] = ()

    target_eligible: bool = False
    target_blockers: tuple[str, ...] = ()

    #: "low" (device path only) | "medium" (some stable fields) |
    #: "high" (serial/wwn/id_path all present) - never fabricated;
    #: :func:`serein.installer.identity.identity_confidence` is the
    #: one place this is computed.
    identity_confidence: str = "low"

    def __post_init__(self) -> None:
        if self.identity_confidence not in _IDENTITY_CONFIDENCE_LEVELS:
            raise ValueError(
                f"identity_confidence={self.identity_confidence!r} must be one of "
                f"{_IDENTITY_CONFIDENCE_LEVELS}"
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["partitions"] = [p.to_dict() for p in self.partitions]
        data["filesystem_signatures"] = list(self.filesystem_signatures)
        data["protection_reasons"] = list(self.protection_reasons)
        data["target_blockers"] = list(self.target_blockers)
        return data


@dataclass(frozen=True)
class DiskInventory:
    disks: tuple[DiskInfo, ...] = ()
    schema_version: int = INSTALLER_DISK_INVENTORY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "disks": [d.to_dict() for d in self.disks],
        }


@dataclass(frozen=True)
class TargetDiskIdentity:
    """A stable fingerprint of a selected target disk (Section 11) -
    never the volatile ``/dev/sdX`` name alone, which is an
    observation, not a stable installation identity (Section 57). Not
    every field must exist; match strength is decided by
    ``serein.installer.identity``, not by this dataclass."""

    serial: str | None = None
    wwn: str | None = None
    id_path: str | None = None
    model: str | None = None
    size_bytes: int | None = None
    observed_device_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TargetResolution:
    """Result of re-matching a captured :class:`TargetDiskIdentity`
    against a freshly re-probed :class:`DiskInventory` (Section 12 -
    TOCTOU protection). ``status="resolved"`` is the only status that
    may ever accompany a non-``None`` ``disk``."""

    status: str
    disk: DiskInfo | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _RESOLUTION_STATUSES:
            raise ValueError(f"status={self.status!r} must be one of {_RESOLUTION_STATUSES}")
        if self.status != "resolved" and self.disk is not None:
            raise ValueError(f"status={self.status!r} must not carry a resolved disk")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "disk": self.disk.to_dict() if self.disk is not None else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlanOperation:
    """One step of a :class:`InstallPlan` (Section 19). Every
    destructive operation must carry the target identity it was
    planned against, so ancestry validation
    (``serein.installer.diskguard.validate_plan_ancestry``) never has
    to re-derive it from a bare device string alone."""

    id: str
    kind: str
    device: str
    target_disk_identity: TargetDiskIdentity
    destructive: bool
    requires_confirmation: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "device": self.device,
            "target_disk_identity": self.target_disk_identity.to_dict(),
            "destructive": self.destructive,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlanBoot:
    """Bootloader targeting (Section 17) -
    ``GRUB_DEVICE_SET ⊆ INSTALL_TARGET_DISK`` is checked against these
    two fields, never inferred."""

    grub_target_device: str
    esp_device: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanValidation:
    valid: bool = False
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class InstallPlan:
    """The machine-readable destructive-operation plan (Section 19).
    ``validation`` defaults to invalid/empty - only
    ``serein.installer.planner.validate_plan`` may ever produce a
    ``valid=True`` plan, and only after every check in Section 20-22
    passes."""

    target: TargetDiskIdentity
    target_device_path: str
    protected_disks: tuple[TargetDiskIdentity, ...]
    operations: tuple[PlanOperation, ...]
    boot: PlanBoot
    validation: PlanValidation = field(default_factory=PlanValidation)
    schema_version: int = INSTALLER_PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target.to_dict(),
            "target_device_path": self.target_device_path,
            "protected_disks": [p.to_dict() for p in self.protected_disks],
            "operations": [op.to_dict() for op in self.operations],
            "boot": self.boot.to_dict(),
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class InstallerLayerBEvidence:
    """Compact, machine-readable Installer Layer-B evidence (Section
    38), extended with every field the closure gate (Section 52)
    requires so ``enforce_installer_layer_b_closure`` never has to
    re-derive a fact this dataclass could have stated honestly.
    Constructed only via :func:`serein.installer.evidence.assemble_installer_layer_b_evidence`
    - every derived boolean (``target_disk_changed``,
    ``protected_disk_hash_unchanged``, ``protected_disk_modification_count``)
    is computed there from real hash pairs, never asserted directly, so
    it can never silently disagree with the hashes it is derived from.
    Never includes a username, hostname, home directory, or a real
    credential - the QA credential is runtime-generated and never
    recorded here (Section 35).
    """

    source_commit: str

    failure_stage: str | None = None
    failure_reason: str | None = None

    installer_backend: str | None = None
    installer_backend_version: str | None = None
    installer_backend_available: bool = False

    target_explicit: bool = False
    target_identity: TargetDiskIdentity | None = None
    target_identity_revalidated: bool = False
    protected_disk_identities: tuple[TargetDiskIdentity, ...] = ()

    plan_valid: bool = False
    all_destructive_ops_on_target: bool = False

    target_disk_before_sha256: str | None = None
    target_disk_after_sha256: str | None = None
    target_disk_changed: bool = False

    protected_disk_before_sha256: tuple[str, ...] = ()
    protected_disk_after_sha256: tuple[str, ...] = ()
    protected_disk_modification_count: int = 0
    protected_disk_hash_unchanged: bool = False

    target_esp_present: bool = False
    target_root_present: bool = False
    protected_esp_unchanged: bool = False

    installation_status: str = "not_performed"
    install_media_removed_for_boot: bool = False

    installed_boot_status: str = "not_performed"
    installed_boot_mode: str | None = None
    installed_boot_marker: str | None = None
    install_media_attached_during_installed_boot: bool = True

    serein_core_present: bool = False
    firstboot_provisioning: str = "unknown"

    autoinstall_mode: str = "qa_only"
    autoinstall_production_default: bool = False

    target_disk_attached: bool = True
    physical_disk_passthrough: bool = False

    schema_version: int = INSTALLER_LAYER_B_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for stage_field in ("installation_status", "installed_boot_status"):
            value = getattr(self, stage_field)
            if value not in _STAGE_STATUSES:
                raise ValueError(f"{stage_field}={value!r} must be one of {_STAGE_STATUSES}")
        if self.firstboot_provisioning not in _FIRSTBOOT_STATES:
            raise ValueError(
                f"firstboot_provisioning={self.firstboot_provisioning!r} must be one of "
                f"{_FIRSTBOOT_STATES}"
            )
        if self.autoinstall_mode not in _AUTOINSTALL_MODES:
            raise ValueError(
                f"autoinstall_mode={self.autoinstall_mode!r} must be one of {_AUTOINSTALL_MODES}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "installer_backend": self.installer_backend,
            "installer_backend_version": self.installer_backend_version,
            "installer_backend_available": self.installer_backend_available,
            "target_explicit": self.target_explicit,
            "target_identity": self.target_identity.to_dict() if self.target_identity else None,
            "target_identity_revalidated": self.target_identity_revalidated,
            "protected_disk_identities": [
                p.to_dict() for p in self.protected_disk_identities
            ],
            "plan_valid": self.plan_valid,
            "all_destructive_ops_on_target": self.all_destructive_ops_on_target,
            "target_disk_before_sha256": self.target_disk_before_sha256,
            "target_disk_after_sha256": self.target_disk_after_sha256,
            "target_disk_changed": self.target_disk_changed,
            "protected_disk_before_sha256": list(self.protected_disk_before_sha256),
            "protected_disk_after_sha256": list(self.protected_disk_after_sha256),
            "protected_disk_modification_count": self.protected_disk_modification_count,
            "protected_disk_hash_unchanged": self.protected_disk_hash_unchanged,
            "target_esp_present": self.target_esp_present,
            "target_root_present": self.target_root_present,
            "protected_esp_unchanged": self.protected_esp_unchanged,
            "installation_status": self.installation_status,
            "install_media_removed_for_boot": self.install_media_removed_for_boot,
            "installed_boot_status": self.installed_boot_status,
            "installed_boot_mode": self.installed_boot_mode,
            "installed_boot_marker": self.installed_boot_marker,
            "install_media_attached_during_installed_boot": (
                self.install_media_attached_during_installed_boot
            ),
            "serein_core_present": self.serein_core_present,
            "firstboot_provisioning": self.firstboot_provisioning,
            "autoinstall_mode": self.autoinstall_mode,
            "autoinstall_production_default": self.autoinstall_production_default,
            "target_disk_attached": self.target_disk_attached,
            "physical_disk_passthrough": self.physical_disk_passthrough,
        }


@dataclass(frozen=True)
class InstallerStatus:
    """``serein installer status`` output - read-only, never probes a
    real disk destructively and never triggers installation
    (Section 24)."""

    installer_backend: str | None
    installer_backend_available: bool
    disk_probe_tool_available: bool
    disk_count_observed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
