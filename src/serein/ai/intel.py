"""Intel GPU AI-compute status.

Deliberately the thinnest of the three vendor modules. Intel's forward
AI-compute path is native PyTorch XPU support (``torch.xpu``) — Intel
Extension for PyTorch (IPEX) is the older, separate-package mechanism
being superseded as XPU support upstreams into PyTorch itself, and is
explicitly **not** Serein's recommended path (S4R Section 32/33; see
docs/ai/intel-strategy.md for the full reasoning and honest sourcing
caveat). Rather than encode a specific package/tool set Serein cannot
currently verify end-to-end, this module reports hardware presence and
topology (reusing S2's classification — never re-probing) plus an
honest, non-boolean XPU-compatibility label — always "unknown" as of
this pass, never "supported" without live verification (S4R
Section 34). Intel iGPU and Arc (discrete) are never treated as
equivalent compute targets (Section 39) — ``kind`` comes straight from
S2's own confidence-scored classification, "unknown" included.
"""

from __future__ import annotations

from serein.ai.models import IntelAIStatus
from serein.hardware.models import GPUPolicyInfo


def detect_intel_status(gpu_policy: GPUPolicyInfo) -> IntelAIStatus:
    intel_classifications = [c for c in gpu_policy.classifications if c.vendor == "Intel"]
    if not intel_classifications:
        return IntelAIStatus(hardware_present=False, kind=None, xpu_compatibility="unknown")

    # Prefer a "discrete" classification if any Intel device has one
    # (Arc is the more AI-relevant part); otherwise report whatever the
    # single/first classification says.
    discrete = next((c for c in intel_classifications if c.kind == "discrete"), None)
    chosen = discrete or intel_classifications[0]

    return IntelAIStatus(
        hardware_present=True,
        kind=chosen.kind,
        xpu_compatibility="unknown",
    )
