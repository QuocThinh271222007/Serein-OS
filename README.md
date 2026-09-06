# Serein OS

Serein OS is an Ubuntu-based workstation integration layer. It is not a
from-scratch Linux distribution: it does not ship its own kernel or package
ecosystem. It orchestrates and configures mature upstream components on top
of Ubuntu LTS for local AI workloads, software development, cybersecurity
research, and privacy-oriented workflows.

**Current development phase: S3 — Development Workstation.** Serein OS is
not yet a usable Linux distribution ISO — disk/image production is S7's
job, not this phase's. S1 (complete) added the desktop *integration
layer*: a declarative KDE Plasma package manifest, `/etc/xdg`
configuration resources, and read-only detection/planning CLI. S2
(complete) added hardware *capability modeling and resource-policy
planning*: `serein hardware capabilities` (what Serein can safely
control on this host) and `serein hardware plan <profile>` (CPU energy
preference, ZRAM/swap, storage I/O schedulers, GPU topology, and
power-profile mapping for the `balanced`, `dev`, `ai`, `battery`, and
`cyber` profiles). S3 turns the `dev` profile into a real development
workstation: it detects existing Python/Node/Rust/Go/C++/Git/GitHub
CLI/Zed/container tooling (`serein dev status`), reports which stacks
Serein can safely provision and where each tool would come from
(`serein dev capabilities`), and produces a deterministic, evidence-based
install plan with no hidden execution (`serein dev plan [component]`).
**No package is installed, no sysfs is written, and no configuration
file is written to any host by this repository** — see
`docs/development/architecture.md`, `docs/hardware/architecture.md`, and
`docs/desktop/installation-plan.md` for exactly which parts of the
install lifecycle exist today versus remain future work.

## Status

See [`docs/roadmap.md`](docs/roadmap.md) for the full phase plan. Desktop
architecture, package strategy, configuration ownership, and known
limitations are documented under [`docs/desktop/`](docs/desktop/).
Hardware capability modeling, resource-policy planning, and known
limitations are documented under [`docs/hardware/`](docs/hardware/).
Development toolchain strategy (Python/Node/Rust/Go/C++/Git/editor/
container) and known limitations are documented under
[`docs/development/`](docs/development/).

## Repository maturity

Pre-alpha. APIs, schemas, and CLI output are expected to change without
notice until the S0 contracts stabilize across a release.
