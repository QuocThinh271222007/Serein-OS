# ADR-0013: AI Backend Selection

## Status

Accepted

## Context

S4 needs a single, deterministic way to answer "which AI compute
backend should this machine target" from S2's existing GPU detection,
without reimplementing hardware probing and without confusing hardware
*presence* with runtime *usability* — the single most common mistake
in this problem space, and one the S4 brief explicitly calls out
(Section 6).

## Decision

- Consume S2's `GPUDevice` list and `GPUPolicyInfo` directly
  (`serein.ai.backend.classify_backend`); never re-probe
  `/sys/class/drm`.
- Priority order when multiple GPU vendors are present: NVIDIA >
  AMD (discrete) > AMD (other) > Intel (discrete/Arc) > Intel
  (other) > unrecognized vendor > CPU. NVIDIA wins every hybrid
  combination because its AI-compute ecosystem is the most mature and
  broadly supported across every S4 target workload (PyTorch, llama.cpp,
  Ollama, vLLM all have first-class CUDA support today).
- A GPU with an unrecognized vendor ID is reported as backend
  `"unknown"`, never silently folded into `"cpu"` — hardware Serein
  cannot classify is surfaced honestly.
- No GPU at all is `"cpu"`, `confidence="high"` — CPU inference is a
  first-class, fully supported mode, not a degraded fallback.
- `classify_backend()` only answers "which backend is the best
  *candidate*"; whether that backend's driver/runtime is actually
  installed and working is a separate question, answered by
  `nvidia.py`/`amd.py`/`intel.py` and surfaced through
  `capabilities.py`'s `usable` field.

## Alternatives considered

- **A single "best GPU" heuristic scoring VRAM/compute capability**:
  rejected — Serein does not have reliable cross-vendor VRAM/compute
  data without vendor-specific runtime tooling already installed
  (chicken-and-egg with the backend classification itself).
- **Encoding a GPU-model support table** for AMD/Intel: rejected, same
  reasoning as ADR for ROCm support (see docs/ai/amd-rocm-strategy.md)
  — such tables go stale immediately and Serein does not maintain one.

## Consequences

- A hybrid Intel+NVIDIA or AMD+NVIDIA laptop always gets NVIDIA as
  the recommended backend, without Serein touching PRIME/GPU-routing
  configuration (S2's existing conservative GPU ownership is
  unchanged).
- `backend.candidates` retains every detected GPU's own classification,
  so a caller wanting the full picture (not just the recommendation)
  has it.
