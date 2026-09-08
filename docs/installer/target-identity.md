# Target Identity Contract (S7.1 Sections 9-12, 33-34, 37)

> Device names such as `/dev/sdb` are observations, not stable
> installation identities.

Linux device enumeration is not stable across a reboot, a re-plug, or
even a rescan within the same boot - `/dev/sdb` today may be `/dev/sdc`
after another device appears or disappears. Every destructive decision
in S7.1 is therefore bound to a **fingerprint**
(`serein.installer.models.TargetDiskIdentity`), never a bare path.

## Capturing identity

`serein.installer.identity.capture_target_identity(disk)` records
whichever of these real fields the disk inventory
(`serein.installer.diskprobe.probe_disks`) actually observed - never
fabricated when absent:

```text
serial
wwn
id_path        (best-effort - a /dev/disk/by-path symlink scan)
model
size_bytes
observed_device_path   (diagnostic only - never trusted alone)
```

`identity_strength()` counts how many of the three STRONG fields
(`serial`, `wwn`, `id_path`) are present. A bare model/size identity
(strength 0) can never resolve to a match on its own -
`identity_matches_disk` requires at least one strong field to actually
be compared before it will ever return `True`.

## No implicit selection (Section 9)

Production installation never uses a policy equivalent to "largest
disk"/"first disk"/"first removable disk"/an empty match. Explicit user
intent (a real device path or serial passed to `serein installer plan
--target <selector>`, or explicit `--target-serial`/
`--target-device-path` flags to `python -m serein.installer
render-autoinstall`) is the only thing that ever binds a target - never
a default.

## TOCTOU re-validation (Section 12)

The disk selected at planning time is re-probed immediately before any
destructive operation - `serein.installer.identity.resolve_target`
matches the captured identity against a freshly re-probed
`DiskInventory` and returns exactly one of:

| status | meaning |
|---|---|
| `resolved` | exactly one disk matches every strong field the identity carries |
| `not_found` | no disk matches (device disappeared, or the identity was too weak to search on) |
| `ambiguous` | more than one disk matches - Section 34: two disks that happen to share every recorded strong field. Fails closed rather than guessing. |
| `changed` | the originally observed device *path* still exists, but its own identity now disagrees with what was captured (e.g. a re-plug put a different disk at the same path) |

Anything except `resolved` blocks (`serein.installer.diskguard.validate_target_selection`
raises with the matching Section 37 failure code -
`TARGET_NOT_FOUND`/`AMBIGUOUS_TARGET`/`TARGET_CHANGED`). The resolver
never falls back to matching by `observed_device_path` alone - that is
exactly the volatile signal this whole module exists not to trust.

## Enumeration-order independence (Section 33)

Because matching is by identity, not position, two disks that swap
device names between the planning scan and the execution scan still
resolve to the correct target - `tests/test_installer.py::TestIdentity::test_resolve_target_survives_device_name_swap`
proves this directly.

## Target-confusion resistance (Section 34)

Two disks sharing the same model/size/transport but distinct serials
are never collapsed into one match -
`test_target_confusion_similar_but_distinct_disks_not_collapsed` proves
the resolver picks the disk whose *serial* actually matches, not the
first "close enough" candidate.

## Install-media exclusion (Section 21, 37)

`TARGET != INSTALL_MEDIA` is enforced structurally:
`validate_target_selection` checks both the resolved disk's own
`install_media` flag and, separately, whether its identity matches any
disk explicitly known to be installation media - either match raises
`TARGET_IS_INSTALL_MEDIA`. S7.1 never attempts an install-to-self
workflow.

## Active/mounted rejection (Section 22, 37)

A target with an active/mounted filesystem is rejected
(`TARGET_ACTIVE`) rather than automatically deactivated. S7.1 never
force-unmounts, force-deactivates LVM/RAID, or otherwise reaches past a
mounted target to make it eligible.
