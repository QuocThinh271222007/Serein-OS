# Serein OS

Serein OS is an Ubuntu-based workstation integration layer. It is not a
from-scratch Linux distribution: it does not ship its own kernel or package
ecosystem. It orchestrates and configures mature upstream components on top
of Ubuntu LTS for local AI workloads, software development, cybersecurity
research, and privacy-oriented workflows.

**Current phase: S0 — Foundation.** Serein OS is not yet a usable Linux
distribution ISO. This repository currently provides an architecture
baseline and a read-only control-plane CLI. No system mutation, package
installation, or desktop customization exists yet.

## Status

See [`docs/roadmap.md`](docs/roadmap.md) for the full phase plan. This
repository is at the very start of that plan (S0).

## Repository maturity

Pre-alpha. APIs, schemas, and CLI output are expected to change without
notice until the S0 contracts stabilize across a release.
