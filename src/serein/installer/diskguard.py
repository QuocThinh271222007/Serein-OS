"""The installer safety gate (S7.1 Sections 8-9, 13, 17, 20-22, 37).

Canonical invariant this whole module exists to enforce as CODE, never
merely documentation (Section 8):

    INSTALL_TARGET_DISK must be explicitly selected AND every
    destructive operation must belong to INSTALL_TARGET_DISK -
    otherwise INSTALL=BLOCKED.

Reuses the same fail-closed, "collect every violated reason, raise
once" idiom as ``serein.distribution.closure.enforce_layer_b_closure``
and the same path-confinement discipline as
``serein.distribution.pathsafety.resolve_within`` - here applied to
*disks* rather than paths. Never an implicit "largest disk"/"first
disk" policy (Section 9) - every function here requires an explicit
identity to check against.
"""

from __future__ import annotations

import re
from dataclasses import replace

from serein.installer.identity import identity_matches_disk
from serein.installer.models import DiskInfo, DiskInventory, InstallPlan, TargetDiskIdentity

#: Precise failure codes (Section 37) - never a generic "installer
#: failed" when one of these applies.
NO_TARGET = "NO_TARGET"
AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
TARGET_CHANGED = "TARGET_CHANGED"
TARGET_IS_INSTALL_MEDIA = "TARGET_IS_INSTALL_MEDIA"
TARGET_ACTIVE = "TARGET_ACTIVE"
PLAN_ESCAPE = "PLAN_ESCAPE"
PROTECTED_DISK_REFERENCE = "PROTECTED_DISK_REFERENCE"
INSTALLER_UNAVAILABLE = "INSTALLER_UNAVAILABLE"
INSTALLER_CONFIG_INVALID = "INSTALLER_CONFIG_INVALID"
INSTALL_FAILED = "INSTALL_FAILED"
INSTALLED_BOOT_FAILED = "INSTALLED_BOOT_FAILED"


class DiskGuardError(ValueError):
    """Raised for any installer safety-gate violation. ``code`` is
    always one of the Section 37 failure codes above, so a caller (CLI,
    evidence assembly) never has to string-match a free-form message to
    know what blocked the install."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


_WHOLE_NVME_MMC_RE = re.compile(r"^/dev/(?:nvme\d+n\d+|mmcblk\d+)$")
_PART_NVME_MMC_RE = re.compile(r"^(/dev/(?:nvme\d+n\d+|mmcblk\d+))p\d+$")
_PART_SIMPLE_RE = re.compile(r"^(/dev/[a-zA-Z]+)\d+$")


def ancestor_disk(device_path: str) -> str:
    """Return the whole-disk device path a partition belongs to
    (Section 20) - e.g. ``/dev/sdb1`` -> ``/dev/sdb``,
    ``/dev/nvme0n1p1`` -> ``/dev/nvme0n1``. A path that is already a
    whole-disk path (no recognized partition suffix) is returned
    unchanged. Purely syntactic - never touches the filesystem."""
    if _WHOLE_NVME_MMC_RE.match(device_path):
        return device_path
    match = _PART_NVME_MMC_RE.match(device_path)
    if match:
        return match.group(1)
    match = _PART_SIMPLE_RE.match(device_path)
    if match:
        return match.group(1)
    return device_path


def classify_protection(inventory: DiskInventory, target_device_path: str) -> DiskInventory:
    """Return a NEW :class:`DiskInventory` with every disk's
    ``protected``/``protection_reasons``/``target_eligible``/
    ``target_blockers`` populated relative to ``target_device_path``
    (Section 13).

    Every disk other than the target is unconditionally
    ``protected=True`` with reason ``"non_target_disk"`` - regardless
    of whether this module could classify it as Windows, install media,
    or anything else (Section 13: "even an unknown non-target disk
    remains protected because NON_TARGET = READ_ONLY"). The target disk
    itself is only ever unprotected if it is genuinely eligible (not
    install media, not mounted) - a "selected" target that turns out to
    be mounted/install-media stays protected, with the specific blocker
    recorded, rather than trusting the selection blindly.
    """
    updated: list[DiskInfo] = []
    for disk in inventory.disks:
        blockers: list[str] = []
        if disk.install_media:
            blockers.append("install_media")
        if disk.mounted:
            blockers.append("mounted")
        eligible = not blockers

        if disk.device_path == target_device_path:
            protected = bool(blockers)
            reasons = tuple(blockers)
        else:
            protected = True
            reasons = ("non_target_disk",)

        updated.append(
            replace(
                disk,
                protected=protected,
                protection_reasons=reasons,
                target_eligible=eligible,
                target_blockers=tuple(blockers),
            )
        )
    return DiskInventory(disks=tuple(updated))


def validate_target_selection(
    target_identity: TargetDiskIdentity | None,
    resolved_disk: DiskInfo | None,
    resolution_status: str,
    install_media_identities: tuple[TargetDiskIdentity, ...] = (),
) -> None:
    """Fail closed unless a target was explicitly selected, uniquely
    and currently re-resolved, and is neither the install media nor
    active/mounted (Sections 9, 12, 21-22, 37). Raises
    :class:`DiskGuardError` with the precise code otherwise; returns
    ``None`` (never a truthy sentinel) on success.
    """
    if target_identity is None:
        raise DiskGuardError(NO_TARGET, "no target disk was explicitly selected")

    if resolution_status == "ambiguous":
        raise DiskGuardError(
            AMBIGUOUS_TARGET, "more than one disk matches the selected target identity"
        )
    if resolution_status == "not_found":
        raise DiskGuardError(
            TARGET_NOT_FOUND, "the selected target disk could not be re-found on re-probe"
        )
    if resolution_status == "changed":
        raise DiskGuardError(
            TARGET_CHANGED,
            "the selected target device path now resolves to a different disk identity",
        )
    if resolution_status != "resolved" or resolved_disk is None:
        raise DiskGuardError(TARGET_NOT_FOUND, "target could not be resolved")

    if resolved_disk.install_media or any(
        identity_matches_disk(media_identity, resolved_disk)
        for media_identity in install_media_identities
    ):
        raise DiskGuardError(
            TARGET_IS_INSTALL_MEDIA, "the selected target resolves to the installation medium"
        )
    if resolved_disk.mounted:
        raise DiskGuardError(
            TARGET_ACTIVE,
            "the selected target has an active/mounted filesystem - refusing to proceed",
        )


def validate_plan_ancestry(plan: InstallPlan, protected_device_paths: tuple[str, ...]) -> None:
    """Every destructive operation's device must resolve (via
    :func:`ancestor_disk`) to ``plan.target_device_path`` (Section 20).
    Additionally, a destructive operation's device (or its ancestor)
    must never literally equal a known protected disk's device path
    (Section 21) - reported as the more specific
    :data:`PROTECTED_DISK_REFERENCE` rather than the generic
    :data:`PLAN_ESCAPE` when that is the reason. Raises
    :class:`DiskGuardError` on the first violation found."""
    for op in plan.operations:
        if not op.destructive:
            continue
        ancestor = ancestor_disk(op.device)
        if op.device in protected_device_paths or ancestor in protected_device_paths:
            raise DiskGuardError(
                PROTECTED_DISK_REFERENCE,
                f"destructive operation {op.id!r} references protected disk "
                f"{ancestor!r} via device {op.device!r}",
            )
        if ancestor != plan.target_device_path:
            raise DiskGuardError(
                PLAN_ESCAPE,
                f"destructive operation {op.id!r} device {op.device!r} does not "
                f"belong to the selected target {plan.target_device_path!r}",
            )


def validate_grub_target(plan: InstallPlan) -> None:
    """``GRUB_DEVICE_SET ⊆ INSTALL_TARGET_DISK`` (Section 17) - the
    bootloader/ESP device must resolve to the selected target, never a
    protected disk."""
    for label, device in (
        ("grub_target_device", plan.boot.grub_target_device),
        ("esp_device", plan.boot.esp_device),
    ):
        if ancestor_disk(device) != plan.target_device_path:
            raise DiskGuardError(
                PLAN_ESCAPE,
                f"boot.{label}={device!r} does not belong to the selected target "
                f"{plan.target_device_path!r}",
            )
