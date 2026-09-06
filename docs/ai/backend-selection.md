# AI Backend Selection

`serein.ai.backend.classify_backend()` answers "which AI compute
backend is the best *candidate* on this hardware" — never "is it
usable" (that's `capabilities.py`'s job, per each vendor module's own
detection). It consumes S2's `GPUDevice` list and `GPUPolicyInfo`
directly; it never re-probes `/sys/class/drm`.

## State machine (priority order, highest first)

| # | Condition                                              | Backend       | Confidence |
|---|----------------------------------------------------------|----------------|------------|
| 1 | Any NVIDIA GPU present                                    | `nvidia_cuda`  | high       |
| 2 | Else any AMD GPU classified "discrete" (medium/high conf) | `amd_rocm`     | medium     |
| 3 | Else any AMD GPU present at all (APU/unknown)             | `amd_rocm`     | low        |
| 4 | Else any Intel GPU classified "discrete" (Arc)            | `intel_gpu`    | low        |
| 5 | Else any Intel GPU present at all (iGPU)                  | `intel_gpu`    | low        |
| 6 | Else any GPU with an unrecognized vendor                  | `unknown`      | low        |
| 7 | Else (no GPU at all)                                       | `cpu`          | high       |

NVIDIA wins every hybrid combination (Intel+NVIDIA, AMD+NVIDIA) — its
AI-compute ecosystem is the most mature and broadly supported across
every target workload (PyTorch, llama.cpp, Ollama, vLLM all have
first-class CUDA support). This mirrors S2's own GPU-topology model:
`gpu.py`'s `classify_gpu_kind()` already treats NVIDIA-vendor presence
as a documented target-market assumption for "discrete," and S4's
backend priority extends that same reasoning one layer up.

"unknown" is never silently folded into "cpu" — a GPU with an
unrecognized vendor ID is real hardware Serein could not classify, and
that is surfaced honestly rather than hidden behind a CPU-only
recommendation.

## Multi-GPU

Every detected GPU gets its own `AIBackendCandidate` entry
(`backend.candidates`); `primary` is the highest-priority one. Multiple
NVIDIA GPUs are all reported, still `nvidia_cuda` as primary — S4 never
configures `NCCL`, GPU affinity, or `CUDA_VISIBLE_DEVICES` (Section 69/70
of the S4 brief); that is the workload's own concern, not Serein's.

## Hybrid laptops

`backend.hybrid` is a straight pass-through of S2's
`GPUPolicyInfo.hybrid` (`True`/`False`/`None` for genuinely unresolved
topology) — S4 never changes PRIME/GPU-routing configuration itself.
Identifying NVIDIA as the AI backend candidate on a hybrid laptop does
not imply Serein will force the discrete GPU globally or touch the
desktop session (S4 brief Section 71).
