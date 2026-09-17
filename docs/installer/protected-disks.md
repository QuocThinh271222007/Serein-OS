# Protected Disk Contract (S7.1 Sections 13-15, 21-22)

> A non-target disk is protected even when its operating system cannot
> be identified.

## The invariant

`serein.installer.diskguard.classify_protection` is the one function
that ever changes a `DiskInfo`'s `protected`/`target_eligible` fields,
and it does so relative to exactly one explicitly selected target
device path:

- **Every disk other than the target is unconditionally `protected=True`**,
  reason `"non_target_disk"` - regardless of whether Windows/install-media/
  mount-state classification succeeded, failed, or was never
  attempted. `NON_TARGET = READ_ONLY` is not contingent on this module
  correctly recognizing what is *on* the disk.
- The target disk itself is only ever unprotected (`protected=False`,
  eligible for destructive operations) if it is genuinely eligible -
  not install media, not mounted. A "selected" target that turns out
  to be mounted or is the install medium **stays protected**, with the
  specific blocker recorded in `protection_reasons`/`target_blockers`,
  rather than trusting the selection blindly.

`serein.installer.models.DiskInfo` defaults to `protected=True`,
`target_eligible=False` - the fail-closed default a caller must
actively overcome via `classify_protection`, never the reverse.

## Windows/install-media classification is best-effort evidence, not the safety boundary

`serein.installer.diskprobe._classify_windows` looks for:

- a FAT32 partition whose label contains `system`/`efi` -> `windows_efi_detected`
- a partition whose label contains `recovery`/`winre` -> `windows_recovery_detected`
- any NTFS filesystem signature -> contributes to `windows_detected`

This is explicitly **not** claimed to be perfect (Section 13: "do not
claim perfect Windows detection"). A disk this heuristic fails to
recognize as Windows-managed is still fully protected as long as it is
not the selected target - the safety invariant never depends on
correct OS identification.

## The intended first physical topology (Section 14)

```text
PC
+-- Internal disk
|   +-- Windows
|   +-- Windows EFI
|   +-- Windows Recovery
|   +-- user data
|
+-- External disk
    +-- selected Serein install target
```

When `target = external disk`, S7.1 guarantees:

```text
Windows disk partition writes = 0
Windows disk filesystem writes = 0
Windows ESP writes = 0
Windows Recovery writes = 0
```

The Windows-style internal disk is never mounted read-write, and its
ESP is never reused for Serein (see `docs/installer/destructive-plan.md`'s
"target self-containment" section) - the initial external-disk
installation contract gives Serein its own GPT + its own ESP + its own
root filesystem on the target disk alone.

## Layer-B proof (Section 31, 44, 46)

The real Installer Layer-B workflow (`docs/installer/vm-validation.md`)
hashes the protected-disk fixture's entire qcow2 image before and after
a real installation run:

```text
PROTECTED_DISK_SHA256_BEFORE == PROTECTED_DISK_SHA256_AFTER
PROTECTED_DISK_MODIFICATION_COUNT == 0
```

`serein.installer.evidence.assemble_installer_layer_b_evidence` derives
both `protected_disk_hash_unchanged` and
`protected_disk_modification_count` directly from the real before/after
hash pairs it is given - never a caller-asserted boolean, and never
vacuously `True` from empty/missing hashes (an early failure that never
reached the hashing stage reports `protected_disk_hash_unchanged=False`,
not a fabricated pass). Because a byte-identical whole-disk hash
trivially implies every sub-region (including the ESP) is also
byte-identical, `protected_esp_unchanged` is derived from the same
comparison rather than a separate check (Section 46).
