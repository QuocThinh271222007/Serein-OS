# S4 — AI Workstation Live Validation Evidence

This directory records the live Ubuntu 26.04 evidence gathered while
authoring S4's package manifest (`src/serein/ai/packages.py`). Tier B
evidence, matching S1R/S2R/S3R/S3's own definition: real `apt`/`dpkg`
package-archive access and real dependency-closure simulation in a
disposable environment — not a full desktop session, and (critically
for S4) not GPU runtime evidence.

## Validation environment

A disposable, isolated **WSL2** instance (`Ubuntu-26.04`, installed via
`wsl.exe --install -d Ubuntu-26.04 --no-launch`), matching every prior
phase's exact methodology — **not** the developer's own running WSL
instance (`Ubuntu-24.04`, confirmed running and untouched throughout,
verified via `wsl -l -v` before and after this session's use).
Unregistered (`wsl.exe --unregister Ubuntu-26.04`) after use.

Confirmed identity:

```
PRETTY_NAME="Ubuntu 26.04 LTS"
VERSION="26.04 (Resolute Raccoon)"
VERSION_CODENAME=resolute
```

`apt-get update` ran clean against `archive.ubuntu.com`/
`security.ubuntu.com` before any package check. No third-party apt
source was configured at any point — confirmed by inspecting
`/etc/apt/sources.list.d/ubuntu.sources` (the only sources file
present) before running any package query, so every package identified
below is unambiguously Ubuntu's own.

## Files

- `ubuntu-package-validation.md` — the headline finding of this pass
  (Ubuntu 26.04 packages both CUDA Toolkit and ROCm directly in its own
  archive — a real correction to an initial assumption carried over
  from older-release knowledge) plus the full package-existence and
  dependency-closure evidence.
- `known-blockers.md` — what GPU-runtime evidence remains unavailable
  in this environment and why, and what that does/doesn't mean for
  S4's correctness.

## What this validation does and does not prove

**Proves:** `ffmpeg`, `cuda-toolkit`, `rocm` (+`rocminfo`/`rocm-smi`),
and `ubuntu-drivers-common` are real, installable Ubuntu 26.04 packages
with a clean, satisfiable dependency closure (396 packages, 0 removals,
0 errors in the combined simulate); `nvidia-container-toolkit` is
confirmed genuinely absent from Ubuntu's own archive (still requires
NVIDIA's own apt repository, as `packages.py` already classified it);
current NVIDIA driver branches available in the archive (up to the
`nvidia-driver-610` series) are real and current, not a stale
470/535-era assumption.

**Does not prove:** anything about NVIDIA/AMD/Intel GPU *runtime*
behavior — no GPU was accessible to the Linux side of the validation
environment (see `known-blockers.md`); that any of `ollama`/
`llama.cpp`/PyTorch's own installers work correctly (deliberately never
executed, in the validation environment or anywhere else); anything
about the exact current NVIDIA driver/CUDA-Toolkit/PyTorch-wheel
compatibility matrix (S4 represents this as a future Apply-time
resolution, never a hardcoded version).
