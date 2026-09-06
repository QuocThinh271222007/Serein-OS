"""Local inference runtime detection: Ollama and llama.cpp.

Ollama and llama.cpp overlap but serve different workflows and may
coexist — coexistence is never flagged as a conflict here or in the
doctor (S4 brief Section 28). ``llama-cli``/``llama-server`` are the
current canonical llama.cpp binary names (renamed from the historical
``main``/``server`` — see docs/ai/inference-strategy.md); both are
probed independently since a source build may produce one without the
other. The Ollama service-active check is a single read-only
``systemctl is-active`` query — Serein never starts, stops, or queries
its private model inventory.
"""

from __future__ import annotations

from serein.ai.models import InferenceStatus, LlamaCppStatus, OllamaStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def _ollama_service_active(runner: CommandRunner) -> bool | None:
    result = runner.run(["systemctl", "is-active", "ollama"], timeout=3.0)
    if result is None:
        return None
    status = result.stdout.strip()
    if status == "active":
        return True
    if status in ("inactive", "failed", "unknown"):
        return False
    return None


def detect_inference_status(runner: CommandRunner = DEFAULT_RUNNER) -> InferenceStatus:
    ollama_binary = probe_tool("ollama", "ollama", runner=runner)
    ollama = OllamaStatus(
        binary=ollama_binary,
        service_active=_ollama_service_active(runner) if ollama_binary.installed else None,
    )
    llama_cpp = LlamaCppStatus(
        llama_cli=probe_tool("llama-cli", "llama-cli", runner=runner),
        llama_server=probe_tool("llama-server", "llama-server", runner=runner),
    )
    return InferenceStatus(ollama=ollama, llama_cpp=llama_cpp)
