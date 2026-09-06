# AMD ROCm Strategy

## The core problem this module solves

ROCm support is architecture-specific, not vendor-wide: "an AMD GPU is
present" is not evidence that ROCm supports *this specific* chip. S4
deliberately does **not** maintain a GPU-model-to-ROCm-support mapping
table — such a table goes stale the moment a new GPU generation ships,
and Serein has no reliable way to map a raw PCI device ID to a
human-readable model name/architecture without one anyway (S4 brief
Section 91).

## The evidence-based alternative: three separate questions (S4R correction)

An earlier revision collapsed three genuinely different questions into
one `supported: bool | None` field, which overstated its own evidence
(Section 11/12 of the S4R corrective). `RocmSupportInfo` now
distinguishes them explicitly:

1. **Is the ROCm runtime installed at all?** (`runtime_installed` — the
   `rocminfo` binary exists.)
2. **Does that runtime enumerate a GPU agent?** (`gpu_enumerated` —
   `rocminfo`'s own output reports a `Device Type: GPU` entry.) This is
   real, local evidence ROCm/HSA recognizes the hardware.
3. **Is PyTorch's own ROCm-wheel/MIOpen/framework-level compatibility
   established** for this exact GPU/framework combination? **This
   module does not answer that question at all.** `gpu_enumerated=True`
   is real hardware-runtime evidence, but it is explicitly never read
   as proof of framework-level compatibility — that gate lives in
   `pytorch.select_pytorch_backend` (see docs/ai/pytorch-strategy.md),
   which stays conservative (`BLOCKED`) even when ROCm enumerates the
   GPU, because no reliable, non-stale source of PyTorch-ROCm
   compatibility data exists for Serein to encode (S4R Section 13,
   Option C: "unknown is acceptable, false certainty is not").

| State                                                  | `runtime_installed` | `gpu_enumerated` | confidence |
|-----------------------------------------------------------|----------------------|-------------------|------------|
| `rocminfo` not installed                                   | `False`              | `None`            | low        |
| `rocminfo` installed, enumerates a `Device Type: GPU`       | `True`               | `True`            | high       |
| `rocminfo` installed, reports no GPU agent                  | `True`               | `False`           | high       |

Because `gpu_enumerated` can only ever be non-`None` when `rocminfo` is
already installed, the planner's `amd.rocm` action (which only governs
the ROCm *runtime* itself, not whether PyTorch should target it)
collapses to two reachable states once AMD hardware is present:
`rocminfo` already installed → `NOOP` (regardless of what it reports —
an installed-but-unsupported combination is the doctor's
`ai_rocm_unsupported_hardware` check's job to `WARN` about, not
something reinstalling ROCm would fix), or `rocminfo` absent →
`BLOCKED` ("support unknown, Serein does not guess from vendor ID
alone"). See `planner.py::_rocm_action`'s docstring for the full
reasoning.

## PyTorch ROCm selection is separately, always conservative

Even when `gpu_enumerated=True` (ROCm's own runtime confirms it
recognizes the GPU), `select_pytorch_backend()` still returns
`target="rocm", status="BLOCKED"` — never `APPLY`. This is a
deliberate policy choice (S4R Section 7/13), not an oversight: hardware
recognition by ROCm's own runtime is not the same claim as "PyTorch's
ROCm wheel is known to work on this exact GPU," and Serein has no
stable source for the latter to encode. A future pass with a verified
compatibility source could relax this; until then, `rocm` never
reaches `APPLY` for a fresh PyTorch install, by design.

## Install source (verified live, corrected from initial assumption)

Ubuntu 26.04 packages ROCm **directly in its own universe archive** —
`rocm` resolves to `7.1.0-0ubuntu6`, `rocminfo` to `7.1.1-0ubuntu1`,
`rocm-smi` to `7.1.1-0ubuntu1`, all from
`archive.ubuntu.com/ubuntu resolute/universe`, confirmed via a
disposable WSL2 instance with no third-party repository configured
(see docs/validation/s4/ubuntu-package-validation.md). This is a real
packaging change from AMD's own `amdgpu-install`-based mechanism,
which older Ubuntu LTS releases required — and exactly the kind of
assumption the S4 brief's Section 4/36 requires verifying rather than
encoding from older guides. `packages.py` classifies `rocm` as
`ubuntu-repository`, not `official-upstream-repository`. Never
executed by S4; represented declaratively only.

## Unsupported-hardware fallback

An AMD GPU ROCm has confirmed unsupported still gets full CPU-inference
support (llama.cpp, Ollama, CPU PyTorch) — S4 never promises GPU
acceleration without real evidence, but it also never treats
unsupported hardware as an AI-profile failure. Vulkan-backed llama.cpp
paths exist upstream for some AMD hardware outside ROCm's own support
matrix; S4 documents this possibility without implementing or
recommending it as a default (not currently verified end-to-end).

## What this module never does

No overclocking, no power-cap/fan-curve tuning, no ROCm environment
variable hacks (e.g. `HSA_OVERRIDE_GFX_VERSION`) recommended as
default behavior — even though such an override is a real, commonly
documented community workaround for near-supported architectures, S4
does not encode it as guidance, since doing so would be exactly the
kind of unverified compatibility claim this module exists to avoid.
