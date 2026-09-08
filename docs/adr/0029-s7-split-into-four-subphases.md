# ADR-0029: S7 Is Split Into 7.0/7.1/7.2/7.3

## Status

Accepted

## Context

"Distribution" as a single monolithic phase would bundle at least four
genuinely separate concerns with very different risk profiles: building
bootable media at all (no host mutation), integrating that media with
Subiquity's real installer flow (the first phase capable of wiping a
real disk), applying Serein's own profile resources to a freshly
installed target (first-boot provisioning), and recovery/rollback if
any of the above goes wrong. Each of these deserves its own scoped
safety review, mirroring the pattern every prior phase (S0-S6.5) already
established of shipping detection/planning before mutation, and now
extending it: shipping *media* before *installation*, and *installation*
before *first-boot configuration* and *recovery*.

## Decision

Split S7 into four sequential sub-phases:

```
S7.0  Bootable ISO prototype        - no installer fork, no first boot, no recovery
S7.1  Installer integration          - first phase that can touch a real disk
S7.2  First-boot provisioning         - applies S0-S6.5 profile resources to a target
S7.3  Recovery / repair / fallback     - recovery partition, rollback, factory reset
```

S7.0 (this repository) implements only the first: prove Serein can be
assembled into real bootable media by remastering a verified upstream
Ubuntu image, without yet inventing a custom installer or provisioning
system. It may still expose upstream Ubuntu installer/live-environment
elements unmodified - that is explicitly acceptable for this
sub-phase.

## Consequences

- S7.0 can ship with zero disk-mutation risk (`S7_0_TARGET_DISK_WRITE_COUNT=0`
  by construction) since it never invokes an installer against a real
  target.
- S7.1's eventual safety review can focus entirely on installer/disk
  concerns without also re-litigating "does the media itself boot
  correctly" - that question is already answered by S7.0.
- A reader of `docs/roadmap.md` sees exactly which sub-phase implements
  which capability, rather than a single "S7 - Distribution" entry that
  could be misread as already covering installation.

## Alternatives considered

**One "S7 - Distribution" phase covering media + installer + first-boot
+ recovery.** Rejected for the same reason S1-S6 each shipped
detection/planning before mutation - bundling "can this media boot at
all" with "can this installer safely wipe a disk" would force S7.0's
review to carry S7.1's risk before S7.0's own scope is even proven
solid.
