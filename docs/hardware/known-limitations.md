# Known Limitations (S2 / S2R)

Explicit per the same "don't overstate what's validated" discipline S1,
S1R, and S2 established.

## Resolved by the S2R micro-corrective

A review found `serein hardware capabilities` could report
`zram_configurable = false` while `serein hardware plan` still returned
`memory.zram = APPLY` for the same machine state — the planner and the
capability model each independently decided whether ZRAM was supported.
Fixed by introducing one shared function
(`memory_policy.detect_zram_capability`) both now call; a bare-metal
host with no proof of kernel ZRAM support now correctly receives
`BLOCKED`, never `APPLY`. This is the only mechanism this consistency
fix was applied to (RAM was the only mechanism found with the gap) —
see `docs/validation/s2r/zram-validation.md`.

## Resolved by S2R (live validation)

The items below were flagged as unverified in S2 and have since been
resolved against a real Ubuntu 26.04 environment (a disposable, isolated
WSL2 instance — see `docs/validation/s2r/`):

- `systemd-zram-generator`'s real package version (1.2.1-2), its actual
  config syntax (`zram-size`, not the obsolete `zram-fraction`/
  `max-zram-size`), its real default values (confirmed matching what
  Serein pins explicitly), and its real config search paths (all 8,
  confirmed against the installed man page) — `docs/validation/s2r/
  zram-validation.md`.
- Whether `/etc/systemd/zram-generator.conf.d/90-serein.conf` collides
  with a package-owned file — confirmed unowned, both via `dpkg-query -S`
  after a real install and via an archive-wide `apt-file` search —
  `docs/validation/s2r/zram-validation.md`.
- Real config-parsing validation: Serein's corrected `zram-size = min(ram
  / 2, 4096)` syntax was used to actually create a real zram device via
  `zram-generator --setup-device`, with the resulting size matching the
  formula against the VM's real RAM.
- Whether `systemd-zram-generator` runs under WSL/containers — confirmed
  it does not (`systemd-detect-virt` reports a container context, and
  the generator declines to run), which is now the basis for Serein's
  own WSL/container ZRAM guard.
- `power-profiles-daemon`'s real package name/version (0.30-2) and exact
  installed marker paths (`/usr/bin/powerprofilesctl`, `/usr/lib/systemd/
  system/power-profiles-daemon.service`) — confirmed to exactly match
  what `power_policy.py` already checked; no code change needed there.

## Still not live-tested

- **Bare-metal `cpufreq` sysfs** (`amd-pstate-epp`/`intel_pstate`(active)/
  `acpi-cpufreq` governor lists, EPP value spelling, driver name
  strings): WSL2 exposes no `cpufreq` sysfs at all (confirmed absent —
  `docs/validation/s2r/cpu-validation.md`), so this remains based on
  well-documented, stable kernel ABI conventions, not a live read.
- **Physical NVMe/SATA/HDD scheduler defaults on real hardware**: WSL2's
  virtual disks expose no `queue/scheduler` file at all (confirmed
  absent), so real-device scheduler *contents* remain unverified —
  though this is now moot for the *policy*, since S2R removed the only
  scheduler recommendation that depended on it (see
  `docs/hardware/storage-policy.md`).
- **Real GPU sysfs** (`device/class`, `device/boot_vga`): WSL2 exposes no
  `/sys/class/drm` card nodes at all, so the corrected classification
  model's structural signals (PCI class `02`, `boot_vga`) are verified
  against documented, stable PCI SIG/kernel conventions, not a live
  read. A physical hybrid-GPU laptop (Intel/AMD iGPU + NVIDIA/AMD dGPU)
  or an Intel Arc system would be needed to close this gap.
- Whether `power-profiles-daemon`'s `performance` profile is actually
  offered on any specific real hardware — by design, Serein never
  assumes this, so this isn't a gap in a claim Serein makes.

A live-VM or physical-hardware validation pass remains the natural next
step for the three bare-metal-only items above before any hardware plan
action graduates to a real Apply mechanism.

## No Apply mechanism exists

`serein hardware plan` is entirely read-only. There is no `serein
hardware apply` command, and none is planned until a dedicated,
sandboxed Apply/Verify/Rollback mechanism is designed and validated in
isolation.

## Per-core CPU heterogeneity is not modeled

Intel P/E-core topology, if present, is not detected or exposed
separately — `cpu_policy.py` reads only `cpu0`. Deferred past S2/S2R by
design.

## Swappiness is unaddressed by design, not oversight

No value is proposed, at any RAM tier, for any profile.

## GPU topology: two residual, documented ambiguities

1. **A solo Intel/AMD GPU cannot be classified integrated-vs-discrete**
   without a PCI ID database, which S2R deliberately does not build
   (Section 19 of the S2R brief). It is honestly reported `"unknown"`
   rather than guessed either way.
2. **`gpu_switching`** always reports `available: null` — no safe,
   sysfs-only mechanism exists to verify PRIME/`switcheroo-control`
   support.

## `serein hardware status`/`doctor`/`plan` on this development host

This repository was developed and tested on a Windows machine with none
of the Linux-specific interfaces S2/S2R reads. Every command degrades
honestly (`not detected`/`unavailable`/`SKIP`) rather than raising — see
the S2R completion report for the exact recorded output on this host.
