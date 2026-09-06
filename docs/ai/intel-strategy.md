# Intel GPU Strategy

Deliberately the thinnest vendor module in S4. Serein has not verified
an end-to-end working path on Ubuntu 26.04 for any part of Intel's AI
compute stack, and declines to encode compatibility claims it cannot
back with evidence (same principle as amd-rocm-strategy.md).

## Forward path: native PyTorch XPU, not Intel Extension for PyTorch (S4R correction)

An earlier revision pointed toward `intel-extension-for-pytorch`
(IPEX) as Serein's Intel tooling recommendation. This has been
corrected (S4R Section 31-33): IPEX is the older, separate-package
mechanism for Intel GPU support, and Intel's own trajectory has been
to upstream XPU support natively into PyTorch itself (`torch.xpu`,
selected via PyTorch's own XPU wheel/index the same way the CUDA/ROCm
variants are — see docs/ai/pytorch-strategy.md and `packages.py`'s
`torch` entry). Serein's manifest therefore carries **no separate
Intel tool entry at all** — XPU is represented purely as one more
`select_pytorch_backend()` target, not a distinct package to install.
IPEX is not part of Serein's manifest and is not recommended.

**Honest sourcing note:** this correction reflects the documented
trajectory of PyTorch's own XPU integration as known at the time of
this pass, not a live-verified 2026 source citation — no live web
research was performed for this specific corrective (see
docs/validation/s4/known-blockers.md). Treat the "IPEX is
superseded/not recommended" framing as directionally correct but
worth re-confirming against PyTorch's own current release notes before
this policy is ever used to justify an Apply action.

## What is detected

`intel.py` reuses S2's own GPU classification (never re-probing
hardware): whether an Intel GPU is present at all, and its `kind`
("integrated" | "discrete" | "unknown", S2's own confidence-scored
classification). If both an iGPU and an Arc (discrete) device are
present, the discrete one is preferred for reporting — but they are
never treated as equivalent compute targets (S4 brief Section 39): a
solo Arc GPU and a solo iGPU produce different `kind` values, and the
Arc's presence never gets attributed to the iGPU or vice versa.

## Compatibility label, not a boolean claim

`IntelAIStatus.xpu_compatibility` is a free-form string ("unknown" is
the only value this pass ever sets) rather than a boolean "supported"
— S4 does not claim Intel AI compute either works or doesn't; it
explicitly declines to make that claim without live verification (see
docs/validation/s4/known-blockers.md for what would be needed).
`select_pytorch_backend()` never returns `target="xpu", status="APPLY"`
as a result — Intel GPU presence always yields `BLOCKED` (S4R
Section 8/34/35), the same conservative treatment ROCm gets when
framework compatibility can't be confirmed.

**S4RM correction (Section 17-19):** the doctor's `ai_pytorch_backend_mismatch`
check originally warned only when `xpu_compatibility != "unknown"` —
which is backwards, since `"unknown"` is the *only* value this pass
ever sets. An installed XPU build with unresolved compatibility is
exactly the state that should surface uncertainty, so the check now
`WARN`s when `build_backend == "xpu"` and compatibility is `"unknown"`
(or the reserved `"unsupported"` value, for a future pass that gains
real negative evidence) — not the reverse.

## What this module never does

No oneAPI/OpenVINO/XPU package installation, no compute-tooling
detection beyond hardware presence — adding those would require live
Ubuntu 26.04 Intel-hardware evidence this pass did not have access to
(see docs/validation/s4/known-blockers.md).
