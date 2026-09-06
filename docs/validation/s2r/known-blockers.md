# S2R — What Remains BLOCKED After This Pass

None of the following are evidence of a defect in the S2R corrections —
each is a gap in what this specific environment (a disposable WSL2 VM,
no physical GPU, no bare-metal cpufreq, no real block-device scheduler)
can exercise, per the same standard applied throughout S1R and S2.

## Bare-metal `cpufreq` (amd-pstate-epp / intel_pstate / acpi-cpufreq)

`S2R_CPU_SYSFS_LIVE=BLOCKED`. WSL2 exposes no `cpufreq` sysfs at all.
The corrected/reviewed CPU policy (Section 29–30 of the S2R brief) rests
on well-documented, stable kernel driver conventions, not a live read.

## Physical NVMe/SATA/HDD scheduler content

`S2R_STORAGE_SYSFS_LIVE=PARTIAL`. WSL2 virtual disks expose no
`queue/scheduler` file at all. This does not weaken the storage policy
correction (Defect E), which no longer depends on scheduler content to
make a recommendation at all.

## Physical hybrid-GPU / Intel Arc validation

`S2R_GPU_SYSFS_LIVE=BLOCKED`. No `/sys/class/drm` card nodes exist under
WSL2. The GPU topology corrective (Defect D) is grounded in documented
PCI SIG/kernel conventions (`device/class` subclass codes,
`device/boot_vga`) rather than a live read — see `gpu-corrective.md` for
why this is still sound without live confirmation.

## Container-runtime-specific re-validation

`S2R_CONTAINER_GUARDS_VALIDATED=PARTIAL`. The container guard shares its
code path with the (live-verified) WSL guard, but no real container
runtime (Docker/Podman) was exercised independently inside the
disposable VM in this pass.

## ZRAM device *runtime* activation via the full generator path

The full `generate` invocation (the real boot-time code path) refuses to
run under WSL2's container-detected virtualization — validated instead
via the lower-level `--setup-device` path, which exercises the same
config parser and device-creation logic. `CONFIG_PARSE_PASS=true`;
`DEVICE_RUNTIME_VIA_GENERATE=BLOCKED` (only reachable on real hardware
or a non-container-detected VM).

## Summary

None of Section 60's high-severity blockers were found. All five
identified defects (A–E) were corrected and, where a live environment
could reach them, verified against a real Ubuntu 26.04 package/kernel —
see `zram-validation.md`, `cpu-validation.md` for what *was* confirmed.
