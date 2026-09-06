# Local Inference Strategy

See ADR-0015 for the full decision record. Ollama and llama.cpp are
both supported and never forced into a single choice — they overlap
but serve genuinely different workflows, and Serein's doctor never
flags their coexistence as a conflict (S4 brief Section 28).

## Ollama — convenient model lifecycle/server UX

Official installer: `ollama.com/install.sh` — no Ubuntu package or apt
repo currently exists; documented in `packages.py`, never executed.
Detection: `ollama --version` (a real binary probe), plus a read-only
`systemctl is-active ollama` query for `service_active` — Serein never
starts, stops, or restarts the service, and never queries Ollama's
private model inventory (no `ollama list`/`ollama ps` call anywhere in
this codebase).

**S4R ownership correction (Section 36-39):** the official installer is
**system-level, not user-level**. It places the binary under
`/usr/local/bin` (root-owned), creates a system `ollama` user/group,
and registers a systemd service — all of which require root. An
earlier revision modeled this as `requires_root=false, risk="low"`,
which understated it; `packages.py`'s `ollama` `ToolDefinition` and
`planner.py`'s `inference.ollama` action now both carry
`requires_root=true, risk="medium"`, and the action's reason documents
that reversal is possible but multi-step (removing the service,
binary, and system user — not a plain file deletion). A future Apply
must not pipe `curl | sh` as its final mechanism: download and verify
the installer/artifact first, then execute in a controlled,
explicit system-mutation step, recording the service/user/group
changes it made (see docs/ai/security.md).

## llama.cpp — lightweight, transparent, portable baseline

No official Ubuntu package — source build or a GitHub Releases
prebuilt asset, both provided by upstream. Current canonical binary
names are `llama-cli` and `llama-server` (renamed from the historical
`main`/`server`); both are probed independently since a source build
may produce one without the other. This is the CPU/low-VRAM-friendly
GGUF baseline — S4 preserves CPU-only viability as a first-class mode
specifically because llama.cpp makes it real, not aspirational.

## vLLM — optional, high-throughput serving

Not part of any default plan action. Primarily a CUDA + Linux
workload; ROCm/CPU support exist upstream but are not assumed
equally mature. Installed (when a user opts in) the same way as the
rest of the Python AI environment — via `uv`, from PyPI, never system
Python. `capabilities.py`'s `vllm` capability always reports
`usable=None` — hardware-dependent usability is not verified by S4.

## ONNX Runtime / TensorRT — optional, cross-vendor / NVIDIA-specific

`onnxruntime` (CPU-portable) and `onnxruntime-gpu` are separate
optional packages; TensorRT is NVIDIA-specific and only ever
meaningfully planned when the detected CUDA/driver stack is already
compatible — never a base dependency for either.

## What this module never does

No `ollama pull`, no automatic model download of any kind, no GGUF
conversion tooling, no quantization workflow — S4 recognizes that
quantized inference is a sensible *recommendation* for constrained
hardware (documented generically, never a specific Q4/Q5 prescription)
without implementing any of the tooling that would produce one.
