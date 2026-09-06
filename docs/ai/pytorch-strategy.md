# PyTorch Strategy

See ADR-0014 for the full decision record. Summary:

- **PyTorch is never installed into system Python.** Exactly S3's
  Python policy: system `python3` is Ubuntu-owned and never a mutation
  target — no plan action anywhere runs `sudo pip install torch` or
  targets the system interpreter's `site-packages`. PyTorch is
  installed via `uv` into a project/AI environment, reusing S3's `uv`
  tooling directly rather than introducing a second Python package
  manager (S4 brief Section 58).
- **Installed via PyTorch's own per-backend index URL**
  (`download.pytorch.org/whl/<cuXXX|rocmX.Y|cpu>` for CUDA/ROCm/CPU,
  PyTorch's native XPU wheel for Intel — never Intel Extension for
  PyTorch, see docs/ai/intel-strategy.md), never plain PyPI for a GPU
  build — this is PyTorch's own documented recommended mechanism, not
  a Serein invention.
- **Backend selection is runtime-gated, never hardware-candidate-only
  (S4R correction, Section 4-9).** A hardware backend candidate
  (`backend.primary`) alone is never sufficient to select an
  accelerator-specific PyTorch build — see "Runtime-gated backend
  selection" below.
- **No hardcoded version pin.** `packages.py`'s `torch` `ToolDefinition`
  documents the index-URL mechanism, not a specific version; a future
  Apply step resolves the exact compatible-current version/index at
  that time.

## Runtime-gated backend selection (S4R correction)

The pre-corrective planner derived the PyTorch build target directly
from `backend.primary` (the hardware candidate) — meaning an NVIDIA
machine with no working driver, or an AMD machine with unconfirmed
ROCm support, would still get `python.pytorch = APPLY` targeting an
accelerator build that had no real chance of working. This is fixed by
`pytorch.select_pytorch_backend()` — the single shared decision
consumed identically by `planner.py`, `capabilities.py`, and
`status.py`, so they can never derive incompatible conclusions (the
same discipline S2RM/S3R established for their own subsystems):

| Backend candidate | Runtime evidence                          | `target` | `status`  |
|--------------------|--------------------------------------------|----------|-----------|
| none (`cpu`)        | n/a                                          | `cpu`    | `APPLY`   |
| `unknown` vendor     | n/a                                           | `cpu`    | `APPLY`   |
| `nvidia_cuda`        | working driver proven (`nvidia-smi` responds) | `cuda`   | `APPLY`   |
| `nvidia_cuda`        | driver NOT proven                             | `cuda`   | `BLOCKED` |
| `amd_rocm`           | `rocminfo` confirms no GPU agent               | `cpu`    | `APPLY`   |
| `amd_rocm`           | `rocminfo` enumerates a GPU agent OR unknown    | `rocm`   | `BLOCKED` |
| `intel_gpu`          | always (XPU compatibility unverified)          | `xpu`    | `BLOCKED` |

`status="BLOCKED"` means Serein does not silently fall back to a CPU
build (that would hide a real, resolvable blocker — e.g. "install the
NVIDIA driver" — from the user) and does not guess an unproven
accelerator build either. Other AI actions (Ollama, llama.cpp) remain
independently plannable regardless, so a `BLOCKED` `python.pytorch`
action never blocks the whole AI profile. See
`models.PyTorchBackendDecision` and `pytorch.select_pytorch_backend`'s
docstrings for the full reasoning, and docs/ai/amd-rocm-strategy.md /
docs/ai/intel-strategy.md for why ROCm/XPU essentially never reach
`APPLY` in this pass (no reliable framework-compatibility source
exists for either).

## Detection: subprocess probe, never an in-process import

Serein's own control-plane process (the `serein` CLI) never imports
`torch` — that would make an ordinarily lightweight status/doctor
command depend on a multi-hundred-megabyte ML framework being
importable (S4 brief Section 60). Instead, `pytorch.py` runs

```
python3 -c "import torch; print(json.dumps({'version': ..., 'cuda': ..., 'hip': ...}))"
```

as a bounded (10s timeout), injectable, read-only subprocess via the
same `CommandRunner` every other S3/S4 detector uses. Importing torch
in a *child* process is an ordinary, safe operation — it loads shared
libraries but does not by itself touch GPU hardware.

## `torch.cuda.is_available()`/`torch.xpu.is_available()` are never called

This is the one deliberate, documented scope limitation: actually
querying CUDA/ROCm/XPU runtime availability requires initializing a
device context, which can hang or crash on a broken driver setup — the
exact failure mode a read-only, bounded-timeout detector must avoid.
`PyTorchStatus.build_backend` reports the *static build variant*
(`torch.version.cuda`/`torch.version.hip`/`torch.version.xpu` — plain
string attributes read at import time, no device access) — never
confirmed runtime usability by direct GPU access.

**S4RM correction (Section 11-16):** the probe originally only checked
`cuda`/`hip`, so a native PyTorch XPU build (no `cuda`/`hip` version,
but a real `xpu` version) fell through to the `else` branch and was
misclassified as `"cpu"`. `torch.version.xpu` is now read the same
static way as the other two, and the classification order is
`cuda` → `hip` (rocm) → `xpu` → `cpu`. `capabilities.py`'s `pytorch_cuda`/
`pytorch_rocm` capabilities derive `usable` from
`select_pytorch_backend()`'s own decision (S4R Section 41 invariant):
`True` only when the installed build's backend matches a confirmed-
ready decision (e.g. a CUDA build with a proven driver), `False` when
installed but the decision doesn't confirm readiness (e.g. a CUDA
build with no working driver — a real, useful mismatch signal, also
surfaced by the doctor's `ai_pytorch_backend_mismatch` check), and
`None` only when nothing is installed at all. `pytorch_cpu` can report
`usable=True` directly, since a CPU build has no external runtime
dependency beyond the interpreter itself.

## Detection scope: whatever `python3` resolves to on PATH

Serein has no fixed "the AI environment" location (S4 brief
Section 46 — no hardcoded data root exists yet). Detection is
therefore scoped to whatever `python3` currently resolves to on
`PATH`, exactly like every other S3/S4 PATH-based tool probe. A
project's own `.venv` must be *active* on `PATH` for Serein to see its
packages — documented as a real, honest limitation in
docs/ai/known-limitations.md, not Serein guessing at a private
project's environment location.

## Transformers baseline

`transformers`, `accelerate`, `safetensors`, `huggingface_hub` — the
default plan action (`python.transformers_baseline`). `datasets`,
`peft`, `trl`, `bitsandbytes`, `flash-attn` are declared (documented,
classified) but deliberately excluded from the default baseline —
workload-specific, platform-compatibility-sensitive, or both.
