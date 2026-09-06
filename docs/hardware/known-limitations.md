# Known Limitations (S2)

Explicit per the same "don't overstate what's validated" discipline S1
and S1R established.

## Not live-tested against a real Ubuntu 26.04 + kernel combination

This phase was developed and tested entirely against fixture trees (this
repository's own Windows/CI development environment has no real
`cpufreq`, `power_supply`, `thermal`, or `zram` sysfs interfaces).
Specifically unverified against live hardware:

- That real `amd-pstate-epp`/`intel_pstate`(active)/`acpi-cpufreq` sysfs
  content matches the exact shape the fixtures model (governor lists,
  EPP value spelling, driver name strings). These are based on
  well-documented, stable kernel ABI conventions, not a live read.
- That `zstd` is actually available as a ZRAM compression algorithm on a
  target Ubuntu 26.04 kernel build (`docs/hardware/memory-policy.md`
  already flags this as unverified and names the fallback).
- Collision risk for `/etc/systemd/zram-generator.conf.d/90-serein.conf`
  against real Ubuntu 26.04 packages — S1R's `dpkg-query -S` method
  would resolve this the same way it resolved the desktop layer's
  `/etc/xdg` question, but has not been run for this path.
- Real NVMe/SATA/HDD scheduler defaults on current Ubuntu 26.04 kernels —
  the `none`-for-NVMe recommendation follows generic kernel-documentation
  reasoning (`docs/hardware/storage-policy.md`), not a live device read.
- Whether `power-profiles-daemon`'s `performance` profile is actually
  offered on any specific real hardware — by design, Serein never assumes
  this (`docs/hardware/power-policy.md`), so this isn't a gap in a claim,
  but it does mean the `ai` profile's PPD mapping is deliberately
  conservative rather than validated as "could have been more specific."

A live-VM validation pass (mirroring S1R's methodology — a disposable,
isolated environment, never the developer's host) is the natural next
step before any hardware plan action graduates to a real Apply mechanism.

## No Apply mechanism exists

`serein hardware plan` is entirely read-only. There is no `serein
hardware apply` command, and none is planned until a dedicated,
sandboxed Apply/Verify/Rollback mechanism is designed and validated in
isolation (see `docs/hardware/planning-and-safety.md`).

## Per-core CPU heterogeneity is not modeled

Intel P/E-core topology, if present, is not detected or exposed
separately — `cpu_policy.py` reads only `cpu0`. This is an accepted S2
simplification, not a hidden gap: Section 17 of the S2 brief explicitly
defers any P/E-core-aware behavior (including process pinning) past S2.

## Swappiness is unaddressed by design, not oversight

See `docs/hardware/memory-policy.md`'s swappiness section — no value is
proposed, at any RAM tier, for any profile.

## GPU switching capability is reported as unknown, not partially guessed

See `docs/hardware/gpu-policy.md` — `gpu_switching` always reports
`available: null`. This is the intended, honest behavior for a mechanism
Serein has no safe, sysfs-only way to verify.

## `serein hardware status`/`doctor`/`plan` on this development host

This repository was developed and tested on a Windows machine with none
of the Linux-specific interfaces S2 reads. Every command degrades
honestly (`not detected`/`unavailable`/`SKIP`) rather than raising — see
the S2 completion report for the exact recorded output on this host.
