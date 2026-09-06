# ADR-0015: Local Inference Runtime Strategy

## Status

Accepted

## Context

Local LLM inference is a primary S4 target workload (direct Eirune
relevance: local 4B-8B quantized inference, RVC/voice workloads,
constrained-VRAM operation). Two mature, complementary open-source
runtimes dominate this space today: Ollama (convenient model
lifecycle/server UX) and llama.cpp (lightweight, transparent, portable
GGUF inference). A third, vLLM, targets high-throughput serving but
has heavier hardware requirements.

## Decision

- **Both Ollama and llama.cpp are supported**, never forced into a
  single choice. They overlap but serve different workflows; the
  doctor never flags their coexistence as a conflict.
- **Ollama**: official installer (`ollama.com/install.sh`) documented,
  never executed. Detection includes a read-only `systemctl is-active`
  query for service state — Serein never starts/stops the service or
  queries its model inventory.
- **llama.cpp**: no official Ubuntu package; source build or GitHub
  Releases prebuilt asset, both documented. Current canonical binaries
  are `llama-cli`/`llama-server` (renamed from `main`/`server`); both
  probed independently.
- **vLLM is optional**, not part of any default plan action — primarily
  a CUDA+Linux workload, and Serein does not assume it works equally on
  all hardware. Installed via `uv` from PyPI when a user opts in.

## GPU-container evaluation for AI (S4-specific, S3 not reopened)

S3's Podman-default general-dev container policy is **not** reversed.
S4 evaluated the current GPU-container ecosystem specifically (S4 brief
Section 42) and found CDI (Container Device Interface,
`nvidia-ctk cdi generate`) is the current, non-obsolete GPU-passthrough
mechanism, and it works with both Docker and Podman — unlike the older
`nvidia-docker2` runtime-wrapper approach, which did materially prefer
Docker. Since the current mechanism is engine-agnostic, there was no
evidence requiring S4 to force a different container engine for AI
workloads; NVIDIA Container Toolkit/CDI detection is layered on top of
S3's existing engine detection instead (see docs/ai/container-strategy.md).

## Alternatives considered

- **Choosing only one of Ollama/llama.cpp**: rejected — the S4 brief
  explicitly requires both, and they genuinely serve different users
  (convenience vs. transparency/portability/CPU viability).
- **Making vLLM part of the default plan**: rejected — its practical
  hardware floor is meaningfully higher than the rest of the baseline,
  and not every AI workstation needs high-throughput serving.

## Consequences

- `serein ai plan inference` proposes both `ollama` and `llama.cpp`
  installation independently; a user may install one, both, or neither.
- `serein ai plan containers` reuses S3's exact Podman-default policy
  unchanged, plus an independent NVIDIA Container Toolkit action gated
  on an actual NVIDIA backend candidate being present.

## S4R addendum: Ollama ownership, and stronger container usability

Two defects found in the S4R corrective pass, both understating real
risk/requirements:

- **Ollama's official installer is system-level, not user-level.** It
  writes to `/usr/local/bin` (root-owned), creates a system `ollama`
  user/group, and registers a systemd service. `requires_root=false,
  risk="low"` was wrong; both `packages.py` and the
  `inference.ollama` plan action now carry `requires_root=true,
  risk="medium"`, with the reason text documenting that reversal is
  possible but multi-step. See docs/ai/inference-strategy.md.
- **NVIDIA AI-container "usable" required too little evidence.**
  `container engine + toolkit installed` was treated as sufficient;
  it now additionally requires a proven working driver AND real CDI
  integration evidence (a spec file or a `nvidia-ctk cdi list`
  read-only query) before `usable=true`. The
  `containers.nvidia_toolkit` plan action is also now `BLOCKED` (not
  `APPLY`) when the driver path is unresolved, mirroring the same
  "prove runtime before provisioning software" discipline
  ADR-0014's addendum applies to PyTorch. See
  docs/ai/container-strategy.md.
