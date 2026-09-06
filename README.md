# Serein OS

Serein OS is an Ubuntu-based workstation integration layer. It is not a
from-scratch Linux distribution: it does not ship its own kernel or package
ecosystem. It orchestrates and configures mature upstream components on top
of Ubuntu LTS for local AI workloads, software development, cybersecurity
research, and privacy-oriented workflows.

**Current development phase: S1 — Desktop.** Serein OS is not yet a usable
Linux distribution ISO — disk/image production is S7's job, not this
phase's. S1 adds the desktop *integration layer*: a declarative KDE
Plasma package manifest, `/etc/xdg` configuration resources, and the
read-only detection/planning CLI described below. **No package is
installed and no configuration file is written to any host by this
repository** — see `docs/desktop/installation-plan.md` for exactly which
parts of the install lifecycle exist today versus remain future work.

## Status

See [`docs/roadmap.md`](docs/roadmap.md) for the full phase plan. Desktop
architecture, package strategy, configuration ownership, and known
limitations are documented under [`docs/desktop/`](docs/desktop/).

## Repository maturity

Pre-alpha. APIs, schemas, and CLI output are expected to change without
notice until the S0 contracts stabilize across a release.
