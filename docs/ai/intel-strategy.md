# Intel GPU Strategy

Deliberately the thinnest vendor module in S4. As of this writing,
Intel's AI compute stack (PyTorch's XPU backend, Intel Extension for
PyTorch, OpenVINO) is real but materially less mature and less
uniformly packaged across distributions than CUDA or ROCm — Serein has
not verified an end-to-end working path on Ubuntu 26.04 for any of it,
and S4 declines to encode compatibility claims it cannot back with
evidence (same principle as amd-rocm-strategy.md).

## What is detected

`intel.py` reuses S2's own GPU classification (never re-probing
hardware): whether an Intel GPU is present at all, and its `kind`
("integrated" | "discrete" | "unknown", S2's own confidence-scored
classification). If both an iGPU and an Arc (discrete) device are
present, the discrete one is preferred for reporting — but they are
never treated as equivalent compute targets (S4 brief Section 39): a
solo Arc GPU and a solo iGPU produce different `kind` values, and the
Arc's presence never gets attributed to the iGPU or vice versa.

## Maturity label, not a boolean claim

`IntelAIStatus.compute_stack_maturity` is a free-form string
("unknown" | "unverified") rather than a boolean "supported" — S4 does
not claim Intel AI compute either works or doesn't; it explicitly
declines to make that claim without live verification (see
docs/validation/s4/known-blockers.md for what would be needed).

## Optional tooling only

`packages.py`'s `intel-extension-for-pytorch` entry is optional and
not part of any default plan action — `serein ai plan` currently has
no Intel-specific action at all (see docs/ai/known-limitations.md).
This is intentional: S4 declined to write a plan action recommending a
tool stack it cannot verify, rather than guess.

## What this module never does

No oneAPI/OpenVINO/XPU package installation, no compute-tooling
detection beyond hardware presence — adding those would require live
Ubuntu 26.04 Intel-hardware evidence this pass did not have access to
(see docs/validation/s4/known-blockers.md).
