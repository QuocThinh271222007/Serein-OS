"""Destructive install-plan construction and validation (S7.1 Sections
16, 19-22).

``build_install_plan`` produces the baseline Serein Alpha layout
(Section 16: GPT + a ~1 GiB FAT32 ESP + the remaining space as ext4
root - no RAID/LVM/ZFS/encryption/separate-/home in this first
baseline). ``validate_plan`` is the one place every safety check from
``serein.installer.diskguard`` is composed together before a plan may
ever be marked ``valid=True`` - never partial, never best-effort.
"""

from __future__ import annotations

from dataclasses import replace

from serein.installer.diskguard import (
    DiskGuardError,
    validate_grub_target,
    validate_plan_ancestry,
)
from serein.installer.models import (
    TARGET_ESP_FILESYSTEM,
    TARGET_ESP_SIZE_BYTES,
    TARGET_ROOT_FILESYSTEM,
    InstallPlan,
    PlanBoot,
    PlanOperation,
    PlanValidation,
    TargetDiskIdentity,
)

#: Partition-numbering convention this planner emits - kept in one
#: place so ``diskguard.ancestor_disk`` (which parses this same
#: convention back apart) and this module never drift apart.
_ESP_PARTITION_SUFFIX = "1"
_ROOT_PARTITION_SUFFIX = "2"


def _partition_device(target_device_path: str, suffix: str) -> str:
    if target_device_path[-1].isdigit():
        # nvme0n1 / mmcblk0-style whole-disk paths need a 'p' separator
        return f"{target_device_path}p{suffix}"
    return f"{target_device_path}{suffix}"


def build_install_plan(
    target_identity: TargetDiskIdentity,
    target_device_path: str,
    protected_disk_identities: tuple[TargetDiskIdentity, ...],
) -> InstallPlan:
    """Build the baseline Serein Alpha destructive plan against an
    already explicitly-selected target (Section 19). Returns an
    UNVALIDATED plan (``validation.valid=False``) - callers must run it
    through :func:`validate_plan` before treating it as safe to render/
    execute."""
    esp_device = _partition_device(target_device_path, _ESP_PARTITION_SUFFIX)
    root_device = _partition_device(target_device_path, _ROOT_PARTITION_SUFFIX)

    operations = (
        PlanOperation(
            id="wipe-partition-table",
            kind="wipe_partition_table",
            device=target_device_path,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason="clear any existing partition table before creating a fresh GPT",
        ),
        PlanOperation(
            id="create-gpt",
            kind="create_gpt",
            device=target_device_path,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason="create a fresh GPT partition table on the selected target",
        ),
        PlanOperation(
            id="create-esp",
            kind="create_esp",
            device=esp_device,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason=f"create the {TARGET_ESP_SIZE_BYTES // (1024 * 1024 * 1024)} GiB EFI System "
                   "Partition",
        ),
        PlanOperation(
            id="format-esp",
            kind="format_fat32",
            device=esp_device,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason=f"format the ESP as {TARGET_ESP_FILESYSTEM}",
        ),
        PlanOperation(
            id="create-root-partition",
            kind="create_root_partition",
            device=root_device,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason="create the Serein root partition using the remaining target space",
        ),
        PlanOperation(
            id="format-root",
            kind="format_ext4",
            device=root_device,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason=f"format the root partition as {TARGET_ROOT_FILESYSTEM}",
        ),
        PlanOperation(
            id="mount-root",
            kind="mount_root",
            device=root_device,
            target_disk_identity=target_identity,
            destructive=False,
            requires_confirmation=False,
            reason="mount the new root filesystem for installation",
        ),
        PlanOperation(
            id="install-system",
            kind="install_system",
            device=root_device,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason="install the base system and Serein payload into the mounted target root",
        ),
        PlanOperation(
            id="install-bootloader",
            kind="install_bootloader",
            device=target_device_path,
            target_disk_identity=target_identity,
            destructive=True,
            requires_confirmation=True,
            reason="install GRUB onto the selected target disk's own ESP - never a protected disk",
        ),
    )

    return InstallPlan(
        target=target_identity,
        target_device_path=target_device_path,
        protected_disks=protected_disk_identities,
        operations=operations,
        boot=PlanBoot(grub_target_device=target_device_path, esp_device=esp_device),
        validation=PlanValidation(valid=False, reasons=("not yet validated",)),
    )


def validate_plan(plan: InstallPlan, protected_device_paths: tuple[str, ...]) -> InstallPlan:
    """Run every plan-safety check (Sections 20-22) and return a NEW
    plan with ``validation`` populated. Never raises on an invalid plan
    - the caller (CLI, evidence assembly) always gets a plan object back
    with an honest ``validation.valid``/``validation.reasons``; only a
    genuinely unexpected internal error propagates. This is the ONE
    place ``validation.valid=True`` may ever be produced."""
    reasons: list[str] = []

    for check in (
        lambda: validate_plan_ancestry(plan, protected_device_paths),
        lambda: validate_grub_target(plan),
    ):
        try:
            check()
        except DiskGuardError as exc:
            reasons.append(str(exc))

    if not plan.operations:
        reasons.append("plan has no operations")

    valid = not reasons
    return replace(plan, validation=PlanValidation(valid=valid, reasons=tuple(reasons)))
