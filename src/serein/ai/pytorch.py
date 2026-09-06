"""PyTorch detection and backend-variant identification.

Uses a bounded, injectable subprocess probe against whatever
``python3`` resolves to on PATH — never an in-process ``import torch``
inside Serein's own control-plane process (S4 brief Section 60/61).
Merely importing torch in a *child* process is an ordinary, safe,
read-only operation (it loads shared libraries but does not touch GPU
hardware); what this module deliberately never does is call
``torch.cuda.is_available()`` or any other API that would actually
initialize a CUDA/ROCm context — that can hang or crash on a broken
driver, and reflects *runtime* usability, not the static build-variant
question this module answers. See docs/ai/pytorch-strategy.md and
docs/ai/known-limitations.md for this documented scope boundary.
"""

from __future__ import annotations

import json

from serein.ai.models import PyTorchStatus
from serein.development.models import ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner

_TORCH_PROBE = (
    "import json\n"
    "try:\n"
    "    import torch\n"
    "except ImportError:\n"
    "    raise SystemExit(1)\n"
    "info = {\n"
    "    'version': torch.__version__,\n"
    "    'cuda': getattr(torch.version, 'cuda', None),\n"
    "    'hip': getattr(torch.version, 'hip', None),\n"
    "}\n"
    "print(json.dumps(info))\n"
)


def detect_pytorch_status(runner: CommandRunner = DEFAULT_RUNNER) -> PyTorchStatus:
    result = runner.run(["python3", "-c", _TORCH_PROBE], timeout=10.0)
    if result is None or result.returncode != 0:
        return PyTorchStatus(installed=ToolStatus(id="torch", installed=False))

    try:
        info = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return PyTorchStatus(installed=ToolStatus(id="torch", installed=False))

    version = info.get("version")
    cuda_version = info.get("cuda")
    hip_version = info.get("hip")

    if cuda_version:
        backend, backend_version = "cuda", cuda_version
    elif hip_version:
        backend, backend_version = "rocm", hip_version
    else:
        backend, backend_version = "cpu", None

    return PyTorchStatus(
        installed=ToolStatus(id="torch", installed=True, version=version),
        build_backend=backend,
        build_backend_version=backend_version,
    )
