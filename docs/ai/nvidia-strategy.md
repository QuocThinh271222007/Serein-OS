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
(`cuda_driver_api_version` vs. `cuda_toolkit_installed`). A host can
have a very recent driver (implying a high CUDA driver-API ceiling)
and zero CUDA Toolkits installed, or vice versa; both are real, valid
states this module represents correctly.

**S4R correction (Section 16-19):** `cuda_toolkit_installed` is now
computed *only* from STRONG evidence — `nvcc --version` succeeding, or
`dpkg` reporting the `cuda-toolkit` package genuinely installed
(reusing `serein.development.dpkg`, not a second package-query
mechanism). A bare `/usr/local/cuda*` directory/symlink existing is
real but weaker evidence — an empty directory or a stale symlink left
over from a partial/removed install previously produced a false
positive here. That marker is now tracked separately as
`cuda_toolkit_marker_present`, never sufficient on its own to set
`cuda_toolkit_installed`; the doctor's `ai_cuda_toolkit_stale_marker`
check `WARN`s when the marker exists without confirmed installation.

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

## CUDA Toolkit is optional, not a default PyTorch prerequisite (S4R correction)

The pre-corrective plan `APPLY`d the CUDA Toolkit by default whenever
a working driver was present. This was too aggressive: **prebuilt
PyTorch CUDA wheels bundle their own required CUDA userspace runtime
libraries** — a local CUDA Toolkit (`nvcc`, native compilation) is
only needed for native CUDA development, source builds, or custom CUDA
extensions, not ordinary wheel-based PyTorch/inference workloads. The
`nvidia.cuda_toolkit` action is therefore never `APPLY` by default: it
is `SKIP` with no NVIDIA hardware, `NOOP` when already installed, and
`NOOP`-as-optional otherwise (reason text explains how to install it
manually, `sudo apt install cuda-toolkit`, once a driver is confirmed,
for workloads that do need `nvcc`). See docs/ai/pytorch-strategy.md for
how PyTorch itself is planned instead — never gated on the Toolkit.

## NVIDIA Container Toolkit / CDI

The current, non-obsolete mechanism for GPU container passthrough is
CDI (Container Device Interface). Current NVIDIA Container Toolkit
releases can generate/manage CDI specs automatically — `nvidia-ctk cdi
generate` is not always a required manual step. CDI works with both
Docker and Podman, so S4 does not force one container engine for GPU
workloads; see docs/ai/container-strategy.md. `containers.py` detects
CDI integration via two read-only sources (S4R Section 27/28): a real,
existing spec file (`/etc/cdi/nvidia.yaml` or `/var/run/cdi/nvidia.yaml`,
existence only) OR a successful `nvidia-ctk cdi list` reporting a real
`nvidia.com/gpu` device entry — Serein never runs `nvidia-ctk cdi
generate` itself.

**S4R correction (Section 25/26/29/30):** GPU-container *usability*
now requires the full chain of evidence, not just "engine + toolkit
installed": a working NVIDIA driver, a container engine, the NVIDIA
Container Toolkit, AND real CDI integration evidence. The
`containers.nvidia_toolkit` plan action is `BLOCKED` (not `APPLY`)
when an NVIDIA backend candidate exists but the driver hasn't been
proven working — provisioning the toolkit before the driver would be
premature.

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
