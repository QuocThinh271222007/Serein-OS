"""Python AI-package detection.

Reuses S3's ``uv`` detection directly rather than re-probing it
(Section 58/86 — ``uv`` remains Serein's one Python environment tool;
S4 does not introduce pipx/poetry/conda as another default). System
Python is never a target for AI packages: Serein has no fixed "AI
environment" location (Section 46 — no hardcoded data root yet), so
detection is scoped to whatever ``python3`` currently resolves to on
``PATH`` — the same PATH-based model every other S3/S4 detector uses.
This is documented as a real, honest limitation (a project's own
``.venv`` must be active on PATH for Serein to see its packages;
see docs/ai/known-limitations.md) rather than Serein guessing at a
private project's environment location.

Every package's presence is read via ``importlib.metadata`` in a
*subprocess* — never an in-process import of the package itself, and
never even an import inside the subprocess (``importlib.metadata``
only reads installed-distribution metadata, it does not execute the
package's own code) — the safest possible detection signal short of
reading site-packages paths directly.
"""

from __future__ import annotations

from serein.ai.models import PythonAIPackagesStatus
from serein.development.models import ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner

_METADATA_PROBE = (
    "import importlib.metadata as m, sys\n"
    "try:\n"
    "    print(m.version('{package}'))\n"
    "except m.PackageNotFoundError:\n"
    "    sys.exit(1)\n"
)


def probe_python_package(
    package: str, dist_name: str | None = None, runner: CommandRunner = DEFAULT_RUNNER
) -> ToolStatus:
    """Detect one installed Python package via ``importlib.metadata``
    (distribution name, which may differ from the import name — e.g.
    the huggingface_hub distribution is registered under that same
    name, so no special-casing is currently required, but the
    parameter exists for whichever package needs it later)."""
    dist_name = dist_name or package
    code = _METADATA_PROBE.format(package=dist_name)
    result = runner.run(["python3", "-c", code], timeout=5.0)
    if result is None or result.returncode != 0:
        return ToolStatus(id=package, installed=False)
    version = result.stdout.strip() or None
    return ToolStatus(id=package, installed=version is not None, version=version)


def detect_python_ai_packages(runner: CommandRunner = DEFAULT_RUNNER) -> PythonAIPackagesStatus:
    return PythonAIPackagesStatus(
        transformers=probe_python_package("transformers", runner=runner),
        accelerate=probe_python_package("accelerate", runner=runner),
        safetensors=probe_python_package("safetensors", runner=runner),
        huggingface_hub=probe_python_package("huggingface_hub", runner=runner),
        vllm=probe_python_package("vllm", runner=runner),
        onnxruntime=probe_python_package("onnxruntime", runner=runner),
        tensorrt=probe_python_package("tensorrt", runner=runner),
        bitsandbytes=probe_python_package("bitsandbytes", runner=runner),
    )
