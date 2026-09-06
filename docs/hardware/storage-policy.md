# Storage Policy: I/O Schedulers

## Detection

`src/serein/hardware/storage_policy.py` reads
`/sys/block/<dev>/queue/scheduler` for every physical block device (same
exclusion list as S0's `storage.py`: loopback, ramdisk, optical,
device-mapper, software-RAID, and ZRAM devices are not physical storage).
The kernel exposes this as one line with the active scheduler in
brackets, e.g. `"mq-deadline [none] bfq"` — both the current value and the
full available list are parsed from that single read.

## Why Serein does not force one scheduler globally

Modern Linux storage is not one thing: an NVMe SSD's own hardware queuing
makes an additional software scheduler largely redundant, a SATA SSD
benefits from a lightweight scheduler like `mq-deadline`, and a spinning
HDD's seek-time characteristics are exactly what `bfq`/`mq-deadline` were
designed to manage well. Blanket-applying one scheduler to every device
(the classic "just use BFQ everywhere" desktop-optimization-guide advice)
ignores this and can measurably hurt NVMe latency for no benefit.

## The one evidence-backed rule Serein does apply

**NVMe devices with `none` in their available scheduler list, not
already set to `none`:** Serein proposes switching to `none`. This is not
a guess — it follows directly from the Linux kernel's own block-layer
documentation: NVMe drives already do their own internal, hardware-level
command queuing and reordering, so an additional software I/O scheduler
adds CPU overhead and latency without improving on what the device
firmware already does at much finer granularity. The action is marked
`confidence: "medium"` (not `"high"`) because Serein cannot verify this
NVMe device's own firmware/queue-depth characteristics — only that `none`
is offered as an option, which on essentially all modern NVMe stacks is a
deliberate signal that it's the intended low-overhead choice.

**Every other case — SATA SSD, HDD, virtual/mapped block devices, or an
NVMe device already at `none`** — the action is always `NOOP`: "no
evidence-backed reason to change this device's current scheduler." There
is no universal "right" scheduler for a SATA SSD or HDD that would
justify Serein overriding whatever Ubuntu's own kernel/udev defaults
already chose.

## Virtualization guard

Under WSL or a container, every `storage.scheduler.<dev>` action reports
`SKIP` — I/O scheduling belongs to the host in both cases. A bare VM
(KVM/VMware/VirtualBox/Hyper-V) is **not** blanket-guarded the same way:
per Section 38 of the S2 brief, a VM's guest-visible block devices (e.g.
a `vda` virtio disk) are treated on their own merits — if the device
exposes a real `queue/scheduler` file, Serein reads and reasons about it
normally (virtio disks are not NVMe-named, so they fall into the
always-`NOOP` bucket above, not the NVMe rule).

## What S2 explicitly does not do

- No mount-option changes, no Btrfs subvolume design, no partitioning, no
  TRIM-schedule changes — all out of S2 scope (mostly S7's).
- No filesystem-type-specific policy — "filesystem-aware limits" from the
  S2 brief are deliberately not implemented; nothing here reads
  `/proc/mounts` or a filesystem's own tuning knobs.
- No serial numbers, WWNs, or filesystem UUIDs are ever read or reported.
