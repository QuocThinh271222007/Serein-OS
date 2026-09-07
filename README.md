# Serein OS

Serein OS is an Ubuntu-based workstation integration layer. It is not a
from-scratch Linux distribution: it does not ship its own kernel or package
ecosystem. It orchestrates and configures mature upstream components on top
of Ubuntu LTS for local AI workloads, software development, cybersecurity
research, and privacy-oriented workflows.

**Current development phase: S6 — Veil / Privacy Isolation.** Serein OS
is not yet a usable Linux distribution ISO — disk/image production is
S7's job, not this phase's. S1 (complete) added the desktop
*integration layer*: a declarative KDE Plasma package manifest,
`/etc/xdg` configuration resources, and read-only detection/planning
CLI. S2 (complete) added hardware *capability modeling and
resource-policy planning*: `serein hardware capabilities` (what Serein
can safely control on this host) and `serein hardware plan <profile>`
(CPU energy preference, ZRAM/swap, storage I/O schedulers, GPU
topology, and power-profile mapping for the `balanced`, `dev`, `ai`,
`battery`, and `cyber` profiles). S3 (complete) turned the `dev`
profile into a real development workstation: Python/Node/Rust/Go/C++/
Git/GitHub CLI/Zed/container tooling detection, capability modeling,
and deterministic planning. S4 (complete) turned the `ai` profile into
a real AI workstation: it classifies which AI compute backend (NVIDIA
CUDA, AMD ROCm, Intel GPU, or CPU) a machine can genuinely target
(`serein ai status`), reports which stacks Serein can safely provision
and whether the underlying runtime is actually usable — never confusing
hardware presence with CUDA/ROCm readiness (`serein ai capabilities`),
and produces a deterministic, evidence-based install plan for drivers,
CUDA/ROCm, PyTorch, Transformers, and local inference runtimes (Ollama,
llama.cpp) with no hidden execution (`serein ai plan [component]`). S5
(complete) extended the existing hardware `cyber` profile into a real
cybersecurity workspace: it classifies which tools belong on the daily
host (light network/capture/reverse-engineering diagnostics), which
belong in an isolated Distrobox/Podman toolbox (specialized/risky
tooling — password audit, exploit frameworks, wireless auditing,
web-security suites), and which require a full VM boundary (Kali,
untrusted binaries, kernel labs) —
`serein cyber status`/`capabilities`/`plan [component]`/`doctor`.
Packet-capture *privilege* is modeled separately from tool presence
(`dumpcap -D`, read-only, never a real capture); Serein is not Kali
Linux and never automates an offensive action. S6 adds a privacy
isolation workspace ("Veil"): Tor client, Tor Browser, DNS-leak, and
Whonix Gateway/Workstation capability modeling and deterministic
planning (`serein veil status`/`capabilities`/`plan [tor|workspace|
whonix]`/`doctor`) — privacy is an explicit, opt-in workspace, never an
invisible global side effect; normal host networking, DNS, firewall
rules, and proxy settings are never mutated by this phase. **No driver,
CUDA/ROCm package, Python package, model file, cyber tool, Tor daemon,
Tor Browser/Whonix image, container, VM, or network namespace is ever
installed/created/captured/scanned/downloaded by this repository** —
see `docs/ai/architecture.md`, `docs/cyber/architecture.md`,
`docs/veil/architecture.md`, `docs/development/architecture.md`,
`docs/hardware/architecture.md`, and `docs/desktop/installation-plan.md`
for exactly which parts of the install lifecycle exist today versus
remain future work.

## Status

See [`docs/roadmap.md`](docs/roadmap.md) for the full phase plan. Desktop
architecture, package strategy, configuration ownership, and known
limitations are documented under [`docs/desktop/`](docs/desktop/).
Hardware capability modeling, resource-policy planning, and known
limitations are documented under [`docs/hardware/`](docs/hardware/).
Development toolchain strategy (Python/Node/Rust/Go/C++/Git/editor/
container) and known limitations are documented under
[`docs/development/`](docs/development/). AI backend/runtime strategy
(NVIDIA/AMD/Intel, PyTorch, local inference, security) and known
limitations are documented under [`docs/ai/`](docs/ai/). Cybersecurity
host/toolbox/VM tiering, packet-capture privilege modeling, and known
limitations are documented under [`docs/cyber/`](docs/cyber/). Veil
privacy-isolation architecture, threat model, Tor/Whonix strategy, and
known limitations are documented under [`docs/veil/`](docs/veil/).

## Repository maturity

Pre-alpha. APIs, schemas, and CLI output are expected to change without
notice until the S0 contracts stabilize across a release.
