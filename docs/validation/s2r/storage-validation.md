# S2R — Storage Validation

Environment: disposable `Ubuntu-26.04` WSL2 instance (see `README.md`).

## Real device inventory

```
$ lsblk
NAME  MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
sda     8:0    0 356.9M  1 disk
sdb     8:16   0 159.4M  1 disk
sdc     8:32   0     4G  0 disk [SWAP]
sdd     8:48   0     1T  0 disk
sde     8:64   0     1T  0 disk /mnt/wslg/distro
                                /
zram0 253:0    0     0B  0 disk
```

Note `sdc` is a real, pre-existing 4 GiB disk-backed swap partition that
WSL2 itself provisions by default — independent confirmation that "WSL
commonly already has real disk swap" (already assumed in the S1/S2
fixture design) is accurate.

## `queue/scheduler` — confirmed absent on every WSL2 virtual disk

```
$ for d in sda sdb sdc sdd sde; do f=/sys/block/$d/queue/scheduler; [ -f "$f" ] && cat "$f" || echo "$d: NO SCHEDULER FILE"; done
sda: NO SCHEDULER FILE
sdb: NO SCHEDULER FILE
sdc: NO SCHEDULER FILE
sdd: NO SCHEDULER FILE
sde: NO SCHEDULER FILE
```

WSL2's virtual-disk driver exposes no I/O scheduler interface at all.
This confirms `storage_policy.py`'s graceful degradation (`SKIP` for a
device with no `queue/scheduler` file) is exercised correctly, but
provides no evidence about real NVMe/SATA/HDD scheduler *content* on
bare metal.

```
S2R_STORAGE_SYSFS_LIVE=PARTIAL   (absence-path confirmed; no positive scheduler-content evidence available)
```

## Why this does not block the storage policy correction

Defect E (removing the speculative "NVMe + none available → APPLY none"
rule) does not depend on live scheduler *content* at all — the
correction is that Serein no longer proposes a scheduler change without
Serein-specific benchmark evidence, regardless of what any device's
scheduler currently is. The correction stands on its own reasoning
(see `docs/hardware/storage-policy.md`), and this environment's absence
of scheduler files does not weaken or strengthen it either way.
