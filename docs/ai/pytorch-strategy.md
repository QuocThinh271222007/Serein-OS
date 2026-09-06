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
  (`download.pytorch.org/whl/<cuXXX|rocmX.Y|cpu>`), never plain PyPI
  for a GPU build — this is PyTorch's own documented recommended
  mechanism, not a Serein invention.
- **Exactly one backend variant is planned per environment**, chosen
  from the classified AI backend (`nvidia_cuda`→cuda,
  `amd_rocm`→rocm, everything else→cpu) — never multiple variants
  installed side by side.
- **No hardcoded version pin.** `packages.py`'s `torch` `ToolDefinition`
  documents the index-URL mechanism, not a specific version; a future
  Apply step resolves the exact compatible-current version/index at
  that time.

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

## `torch.cuda.is_available()` is never called

This is the one deliberate, documented scope limitation: actually
querying CUDA/ROCm runtime availability requires initializing a
device context, which can hang or crash on a broken driver setup — the
exact failure mode a read-only, bounded-timeout detector must avoid.
`PyTorchStatus.build_backend` reports the *static build variant*
(`torch.version.cuda`/`torch.version.hip` — plain string attributes
read at import time, no device access) — never confirmed runtime
usability. `capabilities.py`'s `pytorch_cuda`/`pytorch_rocm`
capabilities always report `usable=None` for this reason; only
`pytorch_cpu` can report `usable=True`, since a CPU build has no
external runtime dependency beyond the interpreter itself.

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
