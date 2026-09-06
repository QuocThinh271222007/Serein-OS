# ADR-0014: PyTorch Environment Isolation

## Status

Accepted

## Context

PyTorch is the primary ML development framework S4 needs to plan for,
but it is a multi-hundred-megabyte, backend-variant-specific (CUDA/
ROCm/CPU) Python package. S3 already established that system Python is
Ubuntu-owned and never a mutation target, and that Serein's own control
plane must stay lightweight and not require heavy runtime dependencies
(S4 brief Section 59/60).

## Decision

- **PyTorch is never installed into system Python.** Reuses S3's `uv`
  tooling directly — no second Python environment manager introduced.
- **Installed via PyTorch's own per-backend index URL**
  (`download.pytorch.org/whl/<cuXXX|rocmX.Y|cpu>`), the officially
  documented mechanism for a GPU build, never plain PyPI for that case.
- **Exactly one backend variant per environment**, chosen from the
  classified AI backend (ADR-0013) — never multiple variants installed
  side by side.
- **Detection via a bounded subprocess probe, never an in-process
  import.** Serein's own CLI process never imports `torch`.
  `pytorch.py` runs `python3 -c "import torch; ..."` in a *child*
  process (10s timeout, injectable `CommandRunner`) to read
  `torch.__version__`/`torch.version.cuda`/`torch.version.hip` —
  static attributes, no device access.
- **`torch.cuda.is_available()` is never called.** It would initialize
  a device context, risking a hang on a broken driver — the exact
  failure mode a bounded, read-only detector must avoid. Only the
  static build-variant is reported; runtime usability is left
  unverified (`usable=None` in `capabilities.py` for
  `pytorch_cuda`/`pytorch_rocm`).

## Alternatives considered

- **`pipx`/`poetry`/`conda` as an AI-specific package manager**:
  rejected per S4 brief Section 58 — `uv` remains the one Python tool,
  matching S3's existing decision (ADR-0009). `micromamba` remains
  optional, only for Conda-ecosystem-specific packages, not the default.
- **Detecting PyTorch via `importlib.metadata` only** (no import):
  considered, but rejected specifically for the backend-variant fields
  — `torch.version.cuda`/`torch.version.hip` are only available after
  import; `importlib.metadata` alone cannot distinguish a CPU wheel
  from a CUDA wheel by version string reliably. (Other, non-variant-
  specific packages — transformers, accelerate, vllm, etc. — do use
  `importlib.metadata` only, in `python_env.py`, since they don't need
  this distinction.)

## Consequences

- PyTorch detection is scoped to whatever `python3` resolves to on
  `PATH` — a project's own `.venv` must be active for Serein to see it
  (documented limitation, docs/ai/known-limitations.md).
- The subprocess-import approach adds real latency (torch import is
  not instant) to `serein ai status`/`capabilities`/`plan` when
  PyTorch is actually installed — an accepted trade-off for safety.

## S4R addendum: runtime-gated backend selection

A defect found in the S4R corrective pass: the *planner* derived the
target backend for a fresh PyTorch install directly from the hardware
candidate (`backend.primary`) alone, with no gating on whether that
backend's runtime was actually usable — an NVIDIA machine with no
working driver still got `python.pytorch = APPLY` targeting a CUDA
build. This decision was never wrong at the *detection* layer (this
ADR's original scope, still accurate), only at the *planning* layer,
which this ADR did not originally cover.

Fixed by `pytorch.select_pytorch_backend()` — one shared decision
function consumed identically by `planner.py`, `capabilities.py`, and
`status.py` (the S2RM/S3R discipline, applied here). See
docs/ai/pytorch-strategy.md's "Runtime-gated backend selection"
section for the full state table. `capabilities.py`'s
`pytorch_cuda`/`pytorch_rocm` `usable` field is no longer
unconditionally `None` — it is derived from this same decision,
producing a real `False` for a genuine mismatch (e.g. a CUDA build
installed with no proven driver).
