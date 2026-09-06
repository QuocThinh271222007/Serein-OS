# Serein OS Roadmap

Phases are sequential; each depends on the ones before it. A phase is not
started implementation-wise until the previous phase's contracts are
stable enough to build on. "No implementation" for a phase's subject in an
earlier phase is intentional, not an oversight.

## S0 — Foundation *(complete, merged to main)*

Architecture principles, repository structure, the Serein CLI foundation,
hardware discovery contract, profile/manifest contract, doctor contract,
installer contract (design only), security/isolation principles, testing
infrastructure, and CI. Produces working, read-only code — not a
documentation-only skeleton.

## S1 — Desktop *(complete, merged to main)*

A lightweight, polished KDE Plasma-based desktop environment, configured
(not forked) via Serein: a declarative package manifest, `/etc/xdg`
configuration resources, a Look-and-Feel package, detection, diagnostics,
and a deterministic installation plan. See
[`docs/desktop/`](desktop/architecture.md) for the full design and
[`docs/adr/0005-kde-plasma-desktop.md`](adr/0005-kde-plasma-desktop.md)
for why KDE Plasma. No package installation or configuration write to any
host happens yet — see `docs/desktop/installation-plan.md`.

## S2 — Hardware *(complete, merged to main)*

Hardware capability modeling (`serein hardware capabilities`) and
resource-policy planning (`serein hardware plan <profile>`) for CPU
energy preference, ZRAM/swap, storage I/O schedulers, GPU topology, and
power-profile mapping, built on the `hardware/` detection module S0
establishes. `serein hardware probe` remains unchanged and
backward-compatible. `balanced`, `dev`, `ai`, `battery`, and `cyber`
gained real hardware-policy manifests in this phase — see
[`docs/hardware/`](hardware/architecture.md) for the full design and
[ADR-0006](adr/0006-hardware-policy-model.md) through
[ADR-0008](adr/0008-upstream-power-management-integration.md). No
sysfs/config write, package install, or Apply mechanism exists yet — see
`docs/hardware/architecture.md` for exactly what "implemented" means at
this phase (the application/tooling layers these profiles will eventually
carry — S3 dev tools, S4 AI runtime, S5 security tooling — remain
entirely separate, unimplemented future work).

## S3 — Development *(this repository, in progress)*

Editor/IDE integration (Zed), language toolchains (Python via uv, Node
via fnm/pnpm, Rust via rustup, Go, C/C++), Git/GitHub CLI, and container
tooling (Podman/Distrobox) for software development workflows. The
`dev` profile's hardware resource-policy layer was implemented in S2;
this phase extends that same profile into a real workload profile
(packages, toolchain source strategy, configuration templates,
verification checks) and adds `serein dev status` (read-only tool
detection), `serein dev capabilities [--json]` (which stacks Serein can
safely provision, and from where), `serein dev doctor [--json]`
(profile/manifest/plan integrity, conflict detection), and
`serein dev plan [component] [--json]` (a deterministic,
evidence-based install plan — `APPLY`/`NOOP`/`SKIP`/`BLOCKED` per
action, never executed). See [`docs/development/`](development/architecture.md)
for the full design and [ADR-0009](adr/0009-python-environment-management.md)
through [ADR-0012](adr/0012-primary-editor-integration.md). No package
install, no `~/.gitconfig`/`~/.config/zed` write, and no Apply
mechanism exists yet — see `docs/development/architecture.md` for
exactly what "implemented" means at this phase.

## S4 — AI

Hardware-detection-driven local AI stack: NVIDIA/AMD/CPU-appropriate
PyTorch, llama.cpp, Ollama, and container-based compute. Builds on the
`gpu`/`cpu` fields in the S0 hardware report and the `ai` profile's S2
hardware resource-policy layer (`docs/hardware/gpu-policy.md`). **No
CUDA or driver installation happens in S0–S2.**

## S5 — Cybersecurity

Isolated security research/authorized-testing environments (container or
VM-based), per [ADR-0004](adr/0004-workload-isolation.md). The `cyber`
profile's hardware resource-policy layer was implemented in S2; the
actual isolated tooling/VM images this phase adds belong here.

## S6 — Veil / Privacy

Tor/Whonix-style privacy workflow isolation, kept separate from the
trusted host per the security model. Not declared as a profile yet in S0
(will be added when this phase starts).

## S7 — Distribution

Installer implementation (built on the S0 installer *contract*, not
before it), recovery integration, and ISO/image production. This is the
first phase that may perform real host mutation, and only within the
Discover → Resolve → Plan → Validate → Apply → Verify → Record lifecycle
defined in `docs/architecture/installer-contract.md`.

## S8 — Refinement & Benchmarking

Apply Integrate → Measure → Replace retroactively across the whole stack:
benchmark first, replace an upstream component only where measurement
shows a demonstrated need. This phase never front-loads into earlier
phases — no component in S0–S7 should be replaced pre-emptively.

## Architecture invariant across all phases

> Serein integrates mature upstream components first, measures their
> behavior, and only replaces them when there is a demonstrated reason.

Every phase above is expected to honor this, not just S8.
