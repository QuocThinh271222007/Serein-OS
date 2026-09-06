# AI Container Strategy

See ADR-0011 (S3, not reopened here) for the general Podman-default
decision and ADR-0015 for how S4's GPU-container evaluation concluded
without reversing it.

## S3's decision stands

S3 chose Podman + Distrobox as the default general-dev container
setup, Docker documented-optional. S4 re-evaluated this specifically
for GPU/AI container workloads (per the S4 brief's explicit instruction
to check whether current NVIDIA/ROCm tooling materially prefers a
different path) and found no evidence requiring a reversal: the
current, non-obsolete GPU-passthrough mechanism is
**CDI (Container Device Interface)**, via `nvidia-ctk cdi generate`,
and CDI works with both Docker and Podman — it does not privilege one
engine over the other the way the older `nvidia-docker2`
runtime-wrapper approach used to. `containers.py`/`planner.py`
therefore keep S3's Podman-first default for the base container
engine, and add NVIDIA Container Toolkit + CDI-marker detection as an
independent layer on top, never a reason to switch engines.

## Detection

`detect_ai_container_status()` reuses S3's
`detect_container_status()` for podman/docker/distrobox directly (no
re-probing) and adds:

- `nvidia_container_toolkit` — an `nvidia-ctk --version` probe.
- `cdi_nvidia_generated` — whether a real CDI spec file exists at
  `/etc/cdi/nvidia.yaml` or `/var/run/cdi/nvidia.yaml` (existence
  only, contents never read; Serein never runs
  `nvidia-ctk cdi generate` itself).

## Planning

`containers.nvidia_toolkit`'s plan action is `SKIP` unless an NVIDIA
backend candidate was actually classified (Section 43 — planning
NVIDIA Container Toolkit on a machine with no NVIDIA GPU at all would
be nonsensical) and the environment isn't itself a nested container.
`containers.engine`'s action mirrors S3's exactly: `NOOP` if either
engine is already present (never a forced choice between them),
`APPLY` podman otherwise, `SKIP` inside a nested container.

## What this module never does

Never starts a container, never runs `nvidia-ctk cdi generate`, never
inspects container contents, never adds a user to a privileged group.
