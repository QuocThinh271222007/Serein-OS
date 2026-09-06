# Storage Policy: I/O Schedulers

## S2R correction notice

S2 proposed automatically switching an NVMe device to the `none`
scheduler whenever it was available and not already selected. **This
has been removed.** It was speculative tuning: Serein had (and still
has) no Serein-specific benchmark evidence that this measurably helps
the mixed workstation workloads Serein targets. Per the governing
principle ("if evidence is insufficient, do not enable it"), the
corrected default is to leave every device's scheduler exactly as the
kernel/upstream set it, on every bus.

## Detection (unchanged)

`src/serein/hardware/storage_policy.py` reads
`/sys/block/<dev>/queue/scheduler` for every physical block device (same
exclusion list as S0's `storage.py`: loopback, ramdisk, optical,
device-mapper, software-RAID, and ZRAM devices are not physical
storage). Both the current scheduler and the full available list are
still detected and exposed — this remains useful, real information for
`serein hardware status`/`capabilities` and for a future S8 benchmark
pass to consume. **Detecting is not the same as recommending changing
it** — see `docs/hardware/planning-and-safety.md`.

## Current default policy: NOOP, always

Every device with a real `queue/scheduler` interface, regardless of bus
(NVMe, SATA SSD, HDD, virtual/mapped), now produces a `NOOP` plan action:
*"No measured Serein-specific evidence justifies replacing the current
upstream scheduler."* A device with no `queue/scheduler` interface at
all (common for virtual/mapped block devices) produces `SKIP`, and a
device under WSL/container virtualization also produces `SKIP` — I/O
scheduling is host-controlled there.

This is deliberately a null policy today. It exists so that:

- The capability (*can* Serein change this) stays visible and testable,
  distinct from the policy (*should* Serein change this) — see
  `docs/hardware/planning-and-safety.md`'s capability-vs-policy section.
- A future, evidence-backed scheduler recommendation (built on real
  benchmark data, per S8) has a real place to plug in without a
  redesign.

## S8 benchmark debt

Scheduler tuning is recorded as a concrete S8 (Refinement & Benchmarking)
topic. Candidate workloads a future benchmark pass should measure before
any scheduler default changes:

```
random read/write IOPS         sequential throughput
compiler workload               AI model loading
desktop responsiveness under I/O    container/database mixed workload
```

No such benchmark is implemented in S2/S2R.

## What S2/S2R still does not do

- No mount-option changes, no Btrfs subvolume design, no partitioning,
  no TRIM-schedule changes.
- No filesystem-type-specific policy.
- No serial numbers, WWNs, or filesystem UUIDs are ever read or
  reported.
