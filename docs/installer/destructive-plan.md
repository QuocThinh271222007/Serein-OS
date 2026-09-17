# Destructive Operation Model (S7.1 Sections 16-22, 25-26)

## Baseline Serein Alpha layout (Section 16)

```text
GPT
Partition 1  EFI System Partition  FAT32   ~1 GiB
Partition 2  Serein root           ext4    remaining usable space
```

No swap partition, no RAID, no LVM, no ZFS, no automatic dual boot, no
partition shrinking, no full-disk/TPM encryption, no separate `/home`
in this first baseline (Section 16) - `serein.installer.planner.build_install_plan`
never emits an operation for any of these.

## The plan (Section 19)

`build_install_plan(target_identity, target_device_path, protected_disk_identities)`
returns a `serein.installer.models.InstallPlan`:

```json
{
  "schema_version": 1,
  "target": { "serial": "...", "wwn": "...", "observed_device_path": "/dev/sdb" },
  "target_device_path": "/dev/sdb",
  "protected_disks": [ ... ],
  "operations": [
    { "id": "wipe-partition-table", "kind": "wipe_partition_table", "device": "/dev/sdb", "destructive": true, ... },
    { "id": "create-gpt", "kind": "create_gpt", "device": "/dev/sdb", "destructive": true, ... },
    { "id": "create-esp", "kind": "create_esp", "device": "/dev/sdb1", "destructive": true, ... },
    { "id": "format-esp", "kind": "format_fat32", "device": "/dev/sdb1", "destructive": true, ... },
    { "id": "create-root-partition", "kind": "create_root_partition", "device": "/dev/sdb2", "destructive": true, ... },
    { "id": "format-root", "kind": "format_ext4", "device": "/dev/sdb2", "destructive": true, ... },
    { "id": "mount-root", "kind": "mount_root", "device": "/dev/sdb2", "destructive": false, ... },
    { "id": "install-system", "kind": "install_system", "device": "/dev/sdb2", "destructive": true, ... },
    { "id": "install-bootloader", "kind": "install_bootloader", "device": "/dev/sdb", "destructive": true, ... }
  ],
  "boot": { "grub_target_device": "/dev/sdb", "esp_device": "/dev/sdb1" },
  "validation": { "valid": false, "reasons": ["not yet validated"] }
}
```

A freshly built plan always starts `validation.valid=false` - only
`serein.installer.planner.validate_plan` may ever flip it to `true`,
and only after every check below passes.

## Ancestry validation (Section 20-21)

`serein.installer.diskguard.ancestor_disk(device_path)` maps a
partition back to its whole-disk device
(`/dev/sdb1 -> /dev/sdb`, `/dev/nvme0n1p1 -> /dev/nvme0n1`,
`/dev/mmcblk0p2 -> /dev/mmcblk0`). For every **destructive** operation,
`validate_plan_ancestry` requires `ancestor_disk(op.device) ==
plan.target_device_path` - a non-destructive operation (`mount_root`)
is not ancestry-checked, since it performs no write of its own.

If a destructive operation's device (or its ancestor) literally equals
a *known protected disk's* device path, the more specific
`PROTECTED_DISK_REFERENCE` failure is raised instead of the generic
`PLAN_ESCAPE` - both block (`PLAN_VALIDATION=FAIL`, `INSTALL=BLOCKED`),
but the more specific code is preserved for diagnosis (Section 37).

## Bootloader targeting (Section 17)

```text
GRUB_DEVICE_SET ⊆ INSTALL_TARGET_DISK
```

`validate_grub_target` checks both `plan.boot.grub_target_device` and
`plan.boot.esp_device` resolve (via `ancestor_disk`) to the selected
target - never a protected disk. For the two-disk Layer-B VM test this
is the direct code behind `GRUB_WRITE_TO_PROTECTED_DISK=false`.

## Target self-containment (Section 15, 47)

The installed target owns its own GPT + its own ESP + its own root
filesystem - the installed system never depends on files stored inside
another disk's ESP, and the Windows-style ESP on a protected disk is
never reused for Serein
(`WINDOWS_ESP_REUSE_FOR_EXTERNAL_TARGET=false`). This is what makes the
"protected disk absent + Serein target present -> Serein still boots"
acceptance scenario meaningful, not merely convenient
(`serein.installer.bootcheck` proves it for real in Layer B).

## UEFI NVRAM (Section 18)

Evidence explicitly distinguishes `target_disk_write` from
`protected_disk_write` from any firmware NVRAM change - the two are
never conflated. The critical safety contract remains
`PROTECTED_DISK_MODIFICATION_COUNT=0`; a self-contained-target-boot
strategy (Section 15) is preferred specifically because it avoids
needing to reason about host/global UEFI NVRAM at all in this first
contract.

## Rendering (Section 25-26)

`serein.installer.renderer.render_autoinstall_storage_config` (and
`render_autoinstall_yaml`, which wraps it) is the **only** thing
allowed to turn a plan into an installer-facing config, and it refuses
to run against a plan whose `validation.valid` is not `True`:

```text
disk evidence -> Serein plan -> Serein safety validation ->
installer config renderer -> Subiquity/curtin
```

Never `raw YAML -> Subiquity` directly. The curtin storage action's
disk `match` stanza is built only from the target's own recorded
identity (serial, then wwn, then the observed path as the final
anchor) - never `largest`/`smallest`/an empty match (Section 26).

See `docs/installer/install-modes.md` for why `render_autoinstall_yaml`
additionally requires an explicit `qa_mode=True` at every call site.
