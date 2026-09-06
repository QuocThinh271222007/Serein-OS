"""AI hardware-backend classification.

Consumes S2's ``GPUDevice`` list and ``GPUPolicyInfo`` — never
re-probes ``/sys/class/drm`` itself (S4 brief Section 5). This module
only answers "which backend is the best AI-compute *candidate* on this
hardware" — it says nothing about whether that backend's runtime is
actually installed/usable, which is nvidia.py/amd.py/intel.py's job
(Section 6).

Backend-selection state machine, in priority order (highest first):

1. Any NVIDIA GPU present -> ``nvidia_cuda`` (confidence "high" — NVIDIA
   has shipped CUDA-capable silicon across its entire relevant current
   product line; this is a documented target-market assumption, the
   same one S2's ``gpu.py`` already makes for ``kind`` classification).
2. Else any AMD GPU classified "discrete" with confidence high/medium
   -> ``amd_rocm`` (confidence "medium" — ROCm support is
   architecture-specific and NOT confirmed here; see amd.py for the
   real runtime-evidence-based support check).
3. Else any AMD GPU present at all (APU/unknown-kind) -> ``amd_rocm``
   (confidence "low" — ROCm's practical floor is discrete GPUs; an APU
   or unclassified AMD part is a much weaker candidate).
4. Else any Intel GPU classified "discrete" (Arc) -> ``intel_gpu``
   (confidence "low" — the compute stack's maturity is still
   documented as uncertain; see intel.py).
5. Else any Intel GPU present at all (iGPU) -> ``intel_gpu``
   (confidence "low").
6. Else any GPU present with an unrecognized vendor -> ``unknown``
   (confidence "low") — hardware exists Serein cannot classify; never
   silently folded into "cpu".
7. Else (no GPU at all) -> ``cpu`` (confidence "high" — CPU inference
   is always a first-class, fully supported mode; see
   docs/ai/backend-selection.md).
"""

from __future__ import annotations

from serein.ai.models import AIBackendCandidate, AIBackendInfo
from serein.hardware.models import GPUDevice, GPUPolicyInfo


def classify_backend(gpus: list[GPUDevice], gpu_policy: GPUPolicyInfo) -> AIBackendInfo:
    candidates: list[AIBackendCandidate] = []
    classifications_by_index = dict(enumerate(gpu_policy.classifications))

    for i, gpu in enumerate(gpus):
        classification = classifications_by_index.get(i)
        kind = classification.kind if classification else (gpu.kind or "unknown")
        conf = classification.confidence if classification else "low"

        if gpu.vendor == "NVIDIA":
            candidates.append(AIBackendCandidate("nvidia_cuda", gpu.vendor, kind, "high"))
        elif gpu.vendor == "AMD":
            if kind == "discrete" and conf in ("high", "medium"):
                candidates.append(AIBackendCandidate("amd_rocm", gpu.vendor, kind, "medium"))
            else:
                candidates.append(AIBackendCandidate("amd_rocm", gpu.vendor, kind, "low"))
        elif gpu.vendor == "Intel":
            candidates.append(AIBackendCandidate("intel_gpu", gpu.vendor, kind, "low"))
        else:
            candidates.append(AIBackendCandidate("unknown", gpu.vendor, kind, "low"))

    priority = {"nvidia_cuda": 0, "amd_rocm": 1, "intel_gpu": 2, "unknown": 3}
    gpu_candidates = [c for c in candidates if c.backend != "unknown"] or [
        c for c in candidates if c.backend == "unknown"
    ]

    if gpu_candidates:
        best = sorted(gpu_candidates, key=lambda c: priority[c.backend])[0]
        primary = best.backend
        primary_confidence = best.confidence
        reason = (
            f"{best.vendor or 'Unrecognized-vendor'} GPU detected "
            f"({best.kind}, classification confidence {best.confidence}); "
            f"{primary} is the AI-compute backend candidate. This does not "
            "mean the corresponding runtime is installed or usable - see "
            "`serein ai capabilities`."
        )
    else:
        primary = "cpu"
        primary_confidence = "high"
        reason = "No GPU detected. CPU inference is a fully supported, first-class mode."

    return AIBackendInfo(
        primary=primary,
        primary_confidence=primary_confidence,
        candidates=candidates,
        hybrid=gpu_policy.hybrid,
        reason=reason,
    )
