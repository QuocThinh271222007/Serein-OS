# S2R — Hardware Policy Corrective and Live Validation Evidence

This directory records the S2R corrective pass: five concrete defects
found in S2's hardware policy design, reproduced, corrected, and
re-validated where a live environment could reach them.

## Validation environment

A disposable, isolated **WSL2** instance (`Ubuntu-26.04`, installed via
`wsl.exe --install -d Ubuntu-26.04`), matching S1R's exact methodology —
**not** the developer's own running WSL instance, and not the Windows
host. Removed (`wsl --unregister`) after use.

Confirmed identity:

```
PRETTY_NAME="Ubuntu 26.04 LTS"
VERSION="26.04 (Resolute Raccoon)"
VERSION_CODENAME=resolute
```

Real `apt`/`dpkg` access confirmed against `archive.ubuntu.com`/
`security.ubuntu.com`. This gives **Tier B** evidence (package
existence/version, config-file syntax parsing via real installed
tooling, `dpkg-query -S` ownership, and — critically — WSL's own
virtualization-detection behavior) but **not** bare-metal `cpufreq`,
physical NVMe/SATA/HDD scheduler content, or real GPU `/sys/class/drm`
evidence, all confirmed absent in this environment (see
`known-blockers.md`).

## Files

- `zram-validation.md` — Defects A, B, C: obsolete config syntax
  claims, empty-directory false positive, overconfident
  `zram_configurable` capability. The most significant findings of this
  pass.
- `cpu-validation.md` — Live confirmation of absent `cpufreq` sysfs
  under WSL2, and confirmation that `power-profiles-daemon`'s real
  package/marker paths match what Serein already checked.
- `storage-validation.md` — Live confirmation of absent
  `queue/scheduler` on WSL2 virtual disks; the storage policy correction
  itself (Defect E) did not depend on live storage evidence.
- `gpu-corrective.md` — Defect D: the GPU topology classification
  model. This module's live sysfs evidence is BLOCKED (no DRM nodes in
  WSL2); the correction is grounded in documented, stable PCI SIG/kernel
  conventions instead.
- `virtualization-validation.md` — WSL/container guard revalidation
  across CPU, storage, and (newly) ZRAM.
- `known-blockers.md` — What remains unverified after this pass, and
  why none of it blocks the corrections made.
