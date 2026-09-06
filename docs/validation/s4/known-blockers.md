# S4 — Known Blockers

What remains unverified after this pass, and why none of it blocks the
corrections/implementation made.

## No GPU runtime evidence (NVIDIA, AMD, or Intel)

The disposable Ubuntu 26.04 WSL2 instance used for package validation
has no Linux-visible GPU device tree — `/sys/class/drm` inside WSL2
does not expose GPU nodes the way S2's hardware detection expects, even
when the Windows host itself has a real, working NVIDIA driver (see
docs/ai/known-limitations.md's "Windows dev-host cross-platform
artifacts" section for the specific, interesting cross-boundary
evidence observed on this dev host: `nvidia-smi.exe` succeeds on
Windows while `/sys/class/drm` sees nothing inside the WSL2 Linux
environment). This means:

```
LIVE_NVIDIA_RUNTIME_VALIDATION=BLOCKED
LIVE_ROCM_RUNTIME_VALIDATION=BLOCKED
LIVE_INTEL_RUNTIME_VALIDATION=BLOCKED
```

None of these were faked. `serein.ai.nvidia`/`amd`/`intel` were
exercised exclusively via unit tests with a `FakeCommandRunner`
providing canned `nvidia-smi`/`rocminfo` output (see `tests/test_ai.py`)
— realistic, evidence-shaped test data, but not a real GPU confirming
the actual runtime behavior end to end.

## Why this does not block the S4 corrections

The corrections made this pass (CUDA Toolkit/ROCm now being
Ubuntu-repository packages) are **package-existence and
dependency-closure** facts, verifiable via `apt`/`dpkg` without any GPU
hardware present — and they were verified. The detection *logic*
(nvidia-smi output parsing, rocminfo GPU-agent-line detection, VRAM
tier classification) is unit-tested against realistic canned output
matching the documented real formats of these tools, which is the
correct scope for a Tier B validation pass. A live GPU would let a
future pass confirm the *parsing* against genuinely live tool output
byte-for-byte — a reasonable next step, not a blocker for this one.

## No live provisioning proof

Same limitation S1R/S2R/S3R/S3 already documented for their own
domains: this pass proves package/metadata facts, never that Ollama's
installer, llama.cpp's build process, or PyTorch's own installer
actually complete successfully on a real machine — S4 has no Apply
engine, so none of these were ever going to be executed regardless of
environment availability.
