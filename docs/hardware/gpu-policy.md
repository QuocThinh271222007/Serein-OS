# GPU Policy

## S2R correction notice

S2's classification (`Intel == integrated`, `AMD == discrete`,
`NVIDIA == discrete`) was a real defect: both AMD and Intel ship
integrated *and* discrete parts (Ryzen/Core APUs, Radeon/Arc discrete
cards), so vendor alone let the probe report confidently *wrong*
classifications (e.g. a solo AMD discrete desktop GPU, or an Intel Arc
card, both previously reported as their opposite kind by construction).
Corrected in two layers — see `docs/validation/s2r/gpu-corrective.md`.

## Layer 1 — `serein.hardware.gpu` (S0, schema-locked `GPUDevice.kind`)

Uses only vendor-independent, structural PCI evidence — the PCI class
code at `device/class` (a stable PCI SIG convention, not vendor-specific):

- Subclass `02` ("3D controller") means the device cannot drive a
  display directly — real, structural proof it's a render/compute-offload
  part, regardless of vendor. Classified `"discrete"`, unconditionally.
- `NVIDIA` remains classified `"discrete"` on vendor alone — a
  documented target-market assumption (NVIDIA does not currently ship
  integrated GPUs Serein would encounter on an Ubuntu workstation), not
  structural proof.
- Everything else — including a solo Intel or AMD GPU with ordinary
  VGA-compatible class (`00`) and no sibling — is honestly `"unknown"`.
  This is a deliberate behavior change: a solo Intel/AMD GPU cannot be
  proven integrated-or-discrete from PCI class alone, and Serein no
  longer guesses. `serein hardware probe`'s output is unchanged in
  *shape* (still `kind: "integrated"|"discrete"|"unknown"|null`, zero
  schema version bump needed) but is now more conservative and more
  honest in *content*.

## Layer 2 — `serein.hardware.gpu_policy` (S2-only, confidence-scored)

Adds one more heuristic signal not used by Layer 1: `device/boot_vga` —
which device the firmware recorded as driving the boot display. This
*can* help disambiguate roles **in a multi-GPU system** (conventionally,
the boot-display device in a laptop with a discrete sibling is the
integrated part), but is worthless in a solo-GPU system (a lone discrete
desktop GPU is `boot_vga=1` and VGA-class too, identical to a lone
integrated GPU) — so it is only applied when more than one GPU is
present. Every classification carries an explicit `confidence`
(`"high"`/`"medium"`/`"low"`), and `hybrid` is a genuine tri-state:

| Scenario | `hybrid` | `hybrid_confidence` |
|---|---|---|
| ≥1 confidently-integrated + ≥1 confidently-discrete, no unresolved devices | `True` | `"high"` (or `"medium"` if any contributing device was itself only medium-confidence) |
| 0 or 1 GPU total | `False` | `"high"` — a solo GPU can never be hybrid regardless of its own kind |
| Multiple GPUs, at least one `"unknown"` | `None` | `"low"` — genuinely unresolved, never guessed |
| Multiple GPUs, all confidently classified, same kind (e.g. dual-NVIDIA) | `False` | `"high"` |

`None` (not `False`) is the honest answer for unresolved multi-GPU
topology — Section 18–21 of the S2R brief's core requirement: uncertainty
is never represented as false certainty.

## What S2R deliberately does not do

- **No PCI ID database.** Distinguishing a solo Intel Arc discrete GPU
  from a solo Intel integrated GPU would require one; Section 19 of the
  S2R brief explicitly rules this out. The residual ambiguity is
  accepted and documented, not hidden.
- **No `nvidia-smi`, no subprocess calls, ever.** GPU detection remains
  entirely sysfs/procfs-based, consistent with every other detector in
  this project.
- **No driver installation, no CUDA/ROCm, no overclocking, no forced GPU
  switching, no unloading drivers, no killing sessions.** Unchanged from
  S2 — these are S4/S7 scope or permanently forbidden.

## NVIDIA compute capability language

`nvidia_compute_gpu` (in `serein hardware capabilities`) means exactly
**"NVIDIA hardware is present"** — confirmed by PCI vendor ID `0x10de` at
a real DRM node. It does **not** mean CUDA is installed, the CUDA runtime
is functional, or a usable compute stack exists — those are S4's
responsibility to establish and verify. The capability's `reason` text is
written to make this distinction unambiguous.

## GPU switching capability: still reported as unknown

`gpu_switching` continues to report `available: null` — no standard,
safely-readable sysfs interface reliably indicates hybrid-GPU switching
support (PRIME/`switcheroo-control`) without invoking vendor tooling or a
desktop-session-specific mechanism outside the hardware-probe layer's
reach.
