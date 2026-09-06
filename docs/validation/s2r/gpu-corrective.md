# S2R — GPU Topology Corrective (Defect D)

## Live evidence status: BLOCKED

```
$ ls /sys/class/drm/
version
```

WSL2 exposes no DRM card nodes at all (not even via WSLg's own GPU
passthrough mechanism, which uses a different, non-`/sys/class/drm`
path). This means the corrected classification model's structural
signals (`device/class`, `device/boot_vga`) could **not** be verified
against a real GPU in this environment.

```
S2R_GPU_SYSFS_LIVE=BLOCKED
```

## Why the correction is still sound without live evidence

The corrected model in `src/serein/hardware/gpu.py` and `gpu_policy.py`
relies on two facts that are **not environment-specific claims** — they
are stable, decades-old PCI SIG and Linux kernel conventions,
independently documentable without needing to observe a specific
machine:

1. **PCI class code `0x0302`** ("3D controller") is a standard PCI SIG
   class/subclass assignment meaning the device has no display output
   capability — this is architecturally true for any PCI device
   reporting that class, on any vendor, on any kernel version. It is
   not a Serein assumption about a specific GPU model.
2. **`device/boot_vga`** is a long-standing Linux kernel sysfs attribute
   (part of the VGA arbiter subsystem) recording which display device
   the firmware handed off to at boot — also not vendor- or
   model-specific.

The actual *correction* being validated is not "does this sysfs file
exist" (which live evidence would confirm) but "is vendor-alone
classification insufficient evidence" — and that claim is validated by
plain, verifiable facts about the GPU market (AMD ships both Ryzen APUs
and Radeon discrete cards; Intel ships both integrated graphics and Arc
discrete cards), not by sysfs content. No live environment is needed to
establish that a defect existed in assuming otherwise.

## What remains open

A physical machine with a hybrid Intel/AMD iGPU + discrete GPU, or an
Intel Arc system, would let a future validation pass confirm the exact
`device/class`/`device/boot_vga` values real hardware reports, closing
the residual gap noted in `docs/hardware/known-limitations.md`. This is
recorded as a non-blocking limitation (Section 61 of the S2R brief:
"physical hybrid GPU / Intel Arc validation" may remain `BLOCKED`
without preventing this corrective from being sound).
