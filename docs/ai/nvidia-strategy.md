# NVIDIA Strategy

See ADR-0013 for the backend-selection decision record. This document
covers the NVIDIA-specific driver/CUDA/container details.

## The driver/toolkit distinction (mandatory, see nvidia.py)

`nvidia-smi`'s banner reports two different things that are commonly
conflated:

- **Driver Version** — the installed kernel driver's own version.
- **CUDA Version** (top-right) — the *maximum* CUDA driver-API version
  that driver supports. This is a property of the *driver*, not proof
  a CUDA *Toolkit* (`nvcc`, `/usr/local/cuda*`) is installed anywhere
  on the system.

`NvidiaStatus` keeps these in separate fields
(`cuda_driver_api_version` vs. `cuda_toolkit_installed`), and
`cuda_toolkit_installed` is computed *only* from independent toolkit
evidence — `nvcc --version` succeeding, or a real `/usr/local/cuda*`
directory/symlink existing (existence check only, never contents read).
A host can have a very recent driver (implying a high CUDA driver-API
ceiling) and zero CUDA Toolkits installed, or vice versa; both are
real, valid states this module represents correctly.

## Driver ownership

Serein prefers Ubuntu's own driver integration
(`ubuntu-drivers autoinstall` / the recommended packaged driver) over
NVIDIA's `.run` installer, which bypasses DKMS/Secure-Boot/kernel-update
integration that Ubuntu's own packaging handles correctly. `nvidia.driver`
plan actions never propose a `.run` installer as the default path — this
is enforced by a regression test (`TestForbiddenActions::test_no_run_installer_recommended`).
Serein does not hardcode a specific driver version/branch number: the
correct choice depends on the host's exact GPU generation and current
Ubuntu/NVIDIA compatibility at Apply-time, which does not exist yet.

## CUDA Toolkit source (verified live, corrected from initial assumption)

Ubuntu 26.04 packages the CUDA Toolkit **directly in its own
multiverse archive** — `cuda-toolkit` resolves to `13.1.1-0ubuntu1`
from `archive.ubuntu.com/ubuntu resolute/multiverse`, confirmed via a
disposable WSL2 instance with no third-party repository configured
(see docs/validation/s4/ubuntu-package-validation.md). This is a real
packaging change from older Ubuntu LTS releases, which required
NVIDIA's own apt repository for a current CUDA Toolkit — and it is
exactly the kind of assumption the S4 brief's Section 4 requires
verifying rather than copying from older guides. `packages.py`
classifies `cuda-toolkit` as `ubuntu-repository`, not
`official-upstream-repository`.

## CUDA Toolkit version policy

Not "latest is best." The version a future Apply step would choose
must be driven by driver compatibility and the target PyTorch build's
supported CUDA minor versions — see `packages.py`'s `cuda-toolkit`
`ToolDefinition` description. The planner's `nvidia.cuda_toolkit`
action is `BLOCKED` (not `APPLY`) when NVIDIA hardware is present but
no working driver was detected — Toolkit compatibility cannot be
safely chosen without knowing the driver first.

## NVIDIA Container Toolkit / CDI

The current, non-obsolete mechanism for GPU container passthrough is
CDI (Container Device Interface) via `nvidia-ctk cdi generate` —
superseding the older `--gpus`/nvidia-docker2-runtime approach. CDI
works with both Docker and Podman, so S4 does not force one container
engine for GPU workloads; see docs/ai/container-strategy.md.
`containers.py` detects a real, existing CDI spec file
(`/etc/cdi/nvidia.yaml` or `/var/run/cdi/nvidia.yaml`, existence only)
as `cdi_nvidia_generated` — Serein never runs `nvidia-ctk cdi generate`
itself.

## VRAM

`nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits` is
the only VRAM source used (real, driver-reported evidence) — AMD/Intel
report no VRAM figure at all rather than guess from a GPU model name.
See docs/ai/known-limitations.md's low-VRAM tier note.

## What this module never does

Never enables persistence mode, never configures CUDA MPS, never sets
`CUDA_VISIBLE_DEVICES`, never stress-tests the GPU, never disables
thermal throttling. All of it is out of scope for a detection/planning
layer with no Apply engine.
