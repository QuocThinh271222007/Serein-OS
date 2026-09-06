"""Intel GPU AI-compute status.

Deliberately the thinnest of the three vendor modules: as of this
writing, Intel's AI compute stack (PyTorch XPU backend / Intel
Extension for PyTorch / OpenVINO) is real but materially less mature
and less universally packaged than CUDA or ROCm (see
docs/ai/intel-strategy.md and docs/validation/s4/ for the sourced
evidence). Rather than encode a specific package/tool set Serein
cannot currently verify end-to-end, this module reports hardware
presence and topology (reusing S2's classification — never
re-probing) plus an honest, non-boolean maturity label. Intel iGPU and
Arc (discrete) are never treated as equivalent compute targets
(Section 39) — ``kind`` comes straight from S2's own confidence-scored
classification, "unknown" included.
"""

from __future__ import annotations

from serein.ai.models import IntelAIStatus
from serein.hardware.models import GPUPolicyInfo


def detect_intel_status(gpu_policy: GPUPolicyInfo) -> IntelAIStatus:
    intel_classifications = [c for c in gpu_policy.classifications if c.vendor == "Intel"]
    if not intel_classifications:
        return IntelAIStatus(hardware_present=False, kind=None, compute_stack_maturity="unknown")

    # Prefer a "discrete" classification if any Intel device has one
    # (Arc is the more AI-relevant part); otherwise report whatever the
    # single/first classification says.
    discrete = next((c for c in intel_classifications if c.kind == "discrete"), None)
    chosen = discrete or intel_classifications[0]

    return IntelAIStatus(
        hardware_present=True,
        kind=chosen.kind,
        compute_stack_maturity="unverified",
    )
