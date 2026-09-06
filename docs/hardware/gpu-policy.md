# GPU Policy

## Detection

`src/serein/hardware/gpu_policy.py` builds on S0's
`serein.hardware.gpu.detect_gpus()` (vendor + integrated/discrete guess
per `/sys/class/drm` node) rather than re-scanning PCI devices itself, and
adds:

- **Hybrid detection:** `hybrid = True` when at least one integrated and
  one discrete GPU are both present (e.g. Intel iGPU + NVIDIA dGPU, AMD
  iGPU + AMD/NVIDIA dGPU).
- **NVIDIA kernel module state:** `/proc/modules` and `/sys/module/nvidia`
  checked independently of whether a DRM node was already classified as
  NVIDIA — a genuinely separate, real signal.
- **amdgpu kernel module state:** same mechanism, for `amdgpu`.

No PCI device/vendor ID beyond what S0 already reads is collected. No
serial numbers, no VRAM totals, no driver version strings.

## What S2 deliberately does not implement

Per the S2 brief's explicit boundary (Sections 33–37), none of the
following exist anywhere in this phase:

- Driver installation (NVIDIA proprietary driver, AMD ROCm) — S4/S7.
- CUDA/ROCm/PyTorch/Ollama/llama.cpp — S4.
- GPU overclocking, power-limit changes, or voltage changes — never, at
  any phase, per the S2 brief's explicit forbidden-optimizations list.
- Forced GPU switching (PRIME/Bumblebee-style), unloading the NVIDIA
  module, or killing a display session — never in S2.
- `nvidia-smi` execution, or any other subprocess call. Serein's hardware
  layer has never shelled out to an external tool anywhere in S0–S2; GPU
  detection is sysfs/procfs-only, same as everything else here. This is
  why "persistence mode," "power state," and "VRAM total" from the S2
  brief's NVIDIA wishlist are **not** implemented: none of them are
  readable without either `nvidia-smi` or the (closed) NVIDIA kernel
  module's own non-standard sysfs extensions, and Serein does not invoke
  external tools to find out.

## Hybrid graphics and the `battery` profile

The only place GPU topology influences a plan action is
`gpu.compute_topology` (informational, `status: "NOOP"` always) under the
`battery` profile: if hybrid graphics are detected, the reason notes that
"the battery profile prefers integrated graphics where the desktop
environment already supports it" — a description of the *intended
outcome*, not an instruction Serein enforces itself. No switching happens
here; if/when Serein integrates with the desktop environment's own
switching mechanism (e.g. `switcheroo-control`, KDE's own PRIME support),
that belongs to S1's desktop layer or a future phase, once measured.

## GPU switching capability: reported as unknown, not guessed

`serein hardware capabilities`' `gpu_switching` entry always reports
`available: null` (not `true`/`false`) with `confidence: "low"`: there is
no standard, safely-readable sysfs interface that reliably indicates
whether hybrid-GPU switching (PRIME offloading, `switcheroo-control`) is
actually usable on a given system without invoking vendor tooling or a
desktop-session-specific mechanism Serein does not have access to at the
hardware-probe layer. Reporting `false` here would be a guess dressed up
as a fact — the S2 brief's "do not simply return booleans when ambiguity
exists" applies directly.
