# Filesystem Strategy (Design Only — Nothing Partitioned in S0)

S0 performs no disk operations of any kind. This document records the
intended future direction so later phases (S2 Hardware, S7 Distribution)
build toward a consistent target instead of improvising per-feature.

## Preferred future layout

```
LUKS2 (full-disk encryption)
  └── Btrfs
        ├── @               (system subvolume)
        ├── @home           (user data)
        ├── @log / @cache   (excluded from snapshots — see below)
        └── @snapshots      (Btrfs snapshots of the above)
```

### Why Btrfs-on-LUKS2

- Snapshots give cheap, fast rollback for system-level changes — a natural
  fit for the installer contract's "Verify → Record" steps and eventual
  rollback support.
- Subvolumes let logs/caches be excluded from snapshots, avoiding
  snapshot bloat from high-churn, low-value data.
- LUKS2 gives full-disk encryption without depending on a specific
  filesystem's native encryption, keeping the storage stack composable.

This is a direction, not a commitment to exact subvolume names or LUKS
parameters — those should be finalized when S7 (Distribution) actually
builds installer media, informed by real measurement per the
Integrate → Measure → Replace principle.

## Large data (AI models, datasets) must not bloat snapshots

A Btrfs snapshot captures whatever is in the snapshotted subvolume at that
moment. Multi-gigabyte AI model weights or datasets sitting inside `@` or
`@home` would make every snapshot expensive and slow. The reserved
direction:

```
/data/
├── models/     large AI model weights
├── datasets/   training/eval datasets
└── projects/   large project working sets, if applicable
```

`/data/` is intended to live outside the snapshotted subvolumes (its own
subvolume, or excluded from the snapshot schedule). This is **not**
mandatory yet — the exact mechanism (separate subvolume vs. bind mount vs.
separate filesystem) is left open until S4 (AI) has real storage
requirements to design against.

## Trade-offs acknowledged, not resolved

- Btrfs snapshot rollback protects the system subvolume, not necessarily
  user data churn in `@home` — retention policy is a later-phase decision.
- LUKS2 password/keyfile/TPM unlock strategy affects boot UX and is
  explicitly deferred to S7.
- None of the above is implemented, tested, or assumed by any command in
  this repository today.
