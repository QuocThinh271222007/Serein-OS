# S4 Known Limitations

Honest accounting of what S4 does and does not prove, matching S1R/S2R/
S3R's own precedent of documenting scope rather than overstating it.

## No production Apply engine

`serein ai plan` describes; it never executes. No driver, CUDA
Toolkit, ROCm, Python package, or model file is ever installed or
downloaded by this codebase. A real Apply engine (S7-adjacent, not
scheduled) would need: privilege escalation handling, a rollback
strategy per action (most AI-stack actions are individually reversible
— `uv`/apt-repo removal — but a driver swap mid-session is not
something Serein should attempt to "undo" automatically), and the
supply-chain verification described in docs/ai/security.md.

## PyTorch/vLLM/Transformers detection is PATH-scoped, not project-aware

Serein has no fixed "the AI environment" location (no hardcoded data
root exists in S4 — see docs/ai/storage-strategy.md). Detection
therefore only sees whatever `python3` resolves to on `PATH` at the
moment a command runs. A project's own `.venv` must be *active* for
Serein to see its installed packages — this is the same PATH-based
model every other S3 detector (`uv`, `node`, `rustup`, ...) already
uses, not a new limitation invented for S4, but it is worth restating
here because AI environments are more commonly per-project than the
dev-tool binaries S3 detects.

## `torch.cuda.is_available()` is never verified

Documented at length in docs/ai/pytorch-strategy.md: S4 reports the
*static build variant* of an installed PyTorch (cuda/rocm/cpu), never
confirmed runtime usability, because verifying it safely would require
initializing a device context — exactly the kind of operation that can
hang on a broken driver, which a bounded, read-only detector must
avoid. `pytorch_cuda`/`pytorch_rocm` capabilities always report
`usable=None` for this reason.

## Intel AI compute stack is unverified end-to-end

`intel.py` reports hardware presence/topology only; no compute-tooling
detection exists, and `serein ai plan` currently has no Intel-specific
action at all. This reflects genuine current uncertainty about the
stack's maturity/packaging on Ubuntu 26.04 (docs/ai/intel-strategy.md),
not an oversight — S4 declined to encode an unverified plan rather than
guess.

## ROCm support is fundamentally per-machine, not per-model

`amd.py`'s design means Serein can only ever confirm ROCm support
*after* ROCm's own tooling is already installed — there is no way to
know in advance for a genuinely clean AMD machine (see
docs/ai/amd-rocm-strategy.md). This is a deliberate, honest limitation:
the alternative (a GPU-ID support table) goes stale immediately and was
explicitly rejected.

## Live validation is Tier B (package/metadata only)

Matching S1R/S2R/S3R's own definition: real `apt`/`dpkg` package-archive
access and real dependency-closure simulation in a disposable Ubuntu
26.04 WSL2 instance, documented in docs/validation/s4/. This is **not**:

- **NVIDIA runtime validation.** The disposable environment (and the
  developer's own host, confirmed via `serein ai status` during
  development) has no accessible Linux-visible NVIDIA GPU — WSL2's
  virtual environment does not expose `/sys/class/drm` GPU nodes the
  way S2's Linux-only hardware detection expects, even when the
  Windows host itself has a real NVIDIA driver (`nvidia-smi` succeeds
  *outside* WSL2's own Linux sysfs view — a genuine, interesting
  cross-boundary artifact observed during this session's own manual
  testing, analogous to S3R's Git-for-Windows `strace.exe` finding).
  `LIVE_NVIDIA_RUNTIME_VALIDATION=BLOCKED`.
- **ROCm runtime validation.** No AMD GPU was available in any
  validation environment used this session. `LIVE_ROCM_RUNTIME_VALIDATION=BLOCKED`.
- **Intel runtime validation.** Same reasoning. `LIVE_INTEL_RUNTIME_VALIDATION=BLOCKED`.
- **A full desktop AI workflow proof.** Package existence and
  dependency-closure evidence is real; an actual working PyTorch/CUDA/
  Ollama session was not exercised end-to-end anywhere in this pass.

## Low-VRAM tiers are a documented convention, not a measured cutoff

The `<6GiB`/`6-8GiB`/`8-12GiB`/`12-24GiB`/`24GiB+` tiers
(`models.classify_vram_tier`) are the exact classes suggested by the S4
brief, chosen for readability rather than a specific measured workload
boundary. They influence recommendations only and never hard-block any
AI capability — consistent with the brief's own instruction (Section 30).

## Windows dev-host cross-platform artifacts

This repository's own development happened on a Windows host with a
real NVIDIA driver installed (Windows' own `nvidia-smi.exe` is on
`PATH` even without a Linux-visible GPU device tree) — `serein ai
status` on this host correctly reports a working NVIDIA driver
(`nvidia-smi` succeeds) while `nvidia.hardware_present` remains `False`
(S2's GPU detection is Linux-`/sys/class/drm`-only). This is **correct,
honest behavior**, not a bug: the driver signal and the hardware-topology
signal come from genuinely different evidence sources, and S4 does not
paper over the discrepancy by picking one arbitrarily.

## No distributed-training platform

S4 supports detecting a PyTorch training-capable environment and
accelerator presence; it does not configure NCCL, GPU affinity, or
install DeepSpeed/Horovod/Ray by default (S4 brief Section 68/69) —
out of scope for a detection/planning layer.
