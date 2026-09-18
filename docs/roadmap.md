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

## S3 — Development *(complete, merged to main)*

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

## S4 — AI *(complete, merged to main)*

Hardware-backend classification (NVIDIA CUDA / AMD ROCm / Intel GPU /
CPU) built on S2's existing GPU detection (never re-probed), NVIDIA
driver/CUDA-Toolkit/container-toolkit detection with the
driver-vs-toolkit distinction enforced by construction, AMD ROCm
support determined only from real `rocminfo` runtime evidence (never
guessed from vendor ID), PyTorch/Transformers-baseline/local-inference
(Ollama, llama.cpp) detection, and deterministic AI planning. The `ai`
profile's hardware resource-policy layer was implemented in S2; this
phase extends that same profile into a real workload profile (same
pattern S3 used for `dev`) and adds `serein ai status`,
`serein ai capabilities [--json]`, `serein ai doctor [--json]`, and
`serein ai plan [component] [--json]`. See [`docs/ai/`](ai/architecture.md)
for the full design and [ADR-0013](adr/0013-ai-backend-selection.md)
through [ADR-0016](adr/0016-ai-model-cache-storage-ownership.md). **No
driver, CUDA Toolkit, ROCm, Python package, or model file is installed
or downloaded by this repository** — see `docs/ai/architecture.md` for
exactly what "implemented" means at this phase. CUDA/PyTorch
installation into the developer's own host never happens; live GPU
runtime evidence is out of scope for this pass (`docs/ai/known-limitations.md`).

## S5 — Cybersecurity *(complete, merged to main)*

Host/toolbox/VM tool tiering for cybersecurity workflows — network
diagnostics, packet-capture privilege modeling, reverse engineering,
web-security testing, password-audit/exploit/wireless tooling, and
forensics — built on the isolation model from
[ADR-0004](adr/0004-workload-isolation.md) and S3's Podman/Distrobox
container architecture (never re-implemented). The `cyber` profile's
hardware resource-policy layer was implemented in S2; this phase
extends that same profile into a real workload profile (same pattern S3
used for `dev` and S4 used for `ai`) and adds `serein cyber status`,
`serein cyber capabilities [--json]`, `serein cyber doctor [--json]`,
and `serein cyber plan [component] [--json]`. See
[`docs/cyber/`](cyber/architecture.md) for the full design and
[ADR-0017](adr/0017-cyber-host-toolbox-vm-tiering.md) through
[ADR-0020](adr/0020-full-kali-and-untrusted-workloads-require-vm.md).
**No cyber tool, container, or VM is ever installed, created, or
scanned by this repository, no packet is ever captured, and no network
is ever scanned** — see `docs/cyber/architecture.md` for exactly what
"implemented" means at this phase. Serein is not Kali Linux; it
classifies and plans, it never automates an offensive action. Real
container/VM provisioning, and any full-Kali or malware-analysis VM
image, remain future work (S7/S8-adjacent, not scheduled).

## S6 — Veil / Privacy *(complete, merged to main)*

Tor client, Tor Browser, DNS-leak, private-workspace, and Whonix
Gateway/Workstation capability modeling and deterministic planning -
kept separate from the trusted host per the security model. Privacy is
an explicit, opt-in workspace boundary, never an invisible global side
effect: normal host networking, DNS, firewall rules, and proxy settings
remain untouched unless a user explicitly enters a Veil workspace. Adds
`serein veil status`, `serein veil capabilities [--json]`,
`serein veil doctor [--json]`, and
`serein veil plan [tor|workspace|whonix] [--json]`. See
[`docs/veil/`](veil/architecture.md) for the full design and
[ADR-0021](adr/0021-veil-privacy-is-opt-in-workspace.md) through
[ADR-0024](adr/0024-no-direct-whonix-workstation-clearnet-egress.md).
**No Tor daemon is started, no system DNS/firewall/proxy is mutated, no
Tor Browser or Whonix image is ever downloaded, no VM/container/network
namespace is ever created, and no external network probe (Tor
connectivity check, public-IP lookup) is ever performed by this
repository** - see `docs/veil/architecture.md` for exactly what
"implemented" means at this phase. No profile is registered for S6 -
see `docs/veil/architecture.md` for why. Real workspace/VM provisioning
remains future work (S7/S8-adjacent, not scheduled).

## S6.5 — Focus Architecture *(planning layer complete, merged to main; real runtime executor added in Phase 7 completion - see below)*

A semantic layer above the normal OS scheduler: many professional
domains (development, AI, cybersecurity, privacy) may exist
simultaneously, but Serein may have at most one PRIMARY focus at any
moment - and PRIMARY never means EXCLUSIVE. Formalizes domain
readiness, one-primary role assignment, and CPU/IO/memory/GPU/
lifecycle *resource intent* (never a mutation) built entirely on
S2-S6's own capability evidence - no second hardware/dev/AI/cyber/
privacy detector exists. Adds `serein focus status`,
`serein focus domains`, `serein focus capabilities [--json]`,
`serein focus plan <target> [--json]`, and
`serein focus transition --from X --to Y [--json]`. See
[`docs/focus/`](focus/architecture.md) for the full design and
[ADR-0025](adr/0025-serein-permits-at-most-one-primary-focus.md)
through
[ADR-0028](adr/0028-gpu-ownership-is-intent-not-generic-enforceable-state.md).
This phase itself never wrote a cgroup, mutated a systemd unit, or
persisted focus state - every S6.5 output carried
`runtime_enforcement: false`, see `docs/focus/architecture.md` for
exactly what "implemented" meant at this phase. `serein.focus.runtime`
(added during the Phase 7 completion program, see ADR-0032) is the
real transaction executor `docs/focus/future-runtime.md` described as
future work - it writes real systemd slice units with real
CPUWeight/IOWeight values and persists real committed focus state,
consuming this phase's planning functions unchanged.

## S7 — Distribution

Split into four sub-phases - see
[ADR-0029](adr/0029-s7-split-into-four-subphases.md) and
[`docs/distribution/s7-roadmap.md`](distribution/s7-roadmap.md).
S7.0 and S7.1 each closed through many real, evidence-driven
corrective rounds; the remaining Phase 7 scope (S7.2, S7.3, and
additional identity/update-infrastructure work the original four-way
split never separately named) was completed as one unified program -
see [ADR-0032](adr/0032-phase-7-completion-strategy.md).

### S7.0 — Bootable ISO Prototype *(complete)*

Proves Serein can be assembled into real, reproducible bootable media by
remastering a verified, checksum-pinned upstream Ubuntu 26.04 LTS
release image with a controlled, integrity-checked Serein payload
overlay - rootless, immutable-base, single-canonical-build-entrypoint,
never a full worktree copy. Adds `serein distribution status` and
`serein distribution inspect <path>` (both read-only), plus explicit
tooling (`distribution/scripts/`) for fetch/verify/build/inspect/
boot-smoke, none of which run implicitly. See
[`docs/distribution/`](distribution/architecture.md) for the full design
and [ADR-0029](adr/0029-s7-split-into-four-subphases.md) through
[ADR-0031](adr/0031-production-iso-preserves-interactive-installer.md).
**No installer is forked or built, no host disk is ever mutated, no
first-boot provisioning exists, and no recovery system exists** - see
`docs/distribution/known-limitations.md` for exactly what "implemented"
means at this phase, including this pass's real (Layer B) validation
status. This is **not** a public release - the project has no selected
license yet (`docs/distribution/licensing-and-release-boundary.md`).

### S7.1 — Installer Integration *(complete)*

Builds on the S0 installer *contract* (not before it) and S7.0's
base-image/payload contracts to integrate real Subiquity-driven target
installation. This is the first phase that may perform real host
mutation, and only within the Discover → Resolve → Plan → Validate →
Apply → Verify → Record lifecycle defined in
`docs/architecture/installer-contract.md`. See `docs/installer/` for
the full design (target-identity contract, protected-disk contract,
destructive-operation model, production-vs-QA install modes, VM
validation topology) and `docs/installer/known-limitations.md` for
exactly what real (Layer B) validation does and does not exist yet.
Closed through many real corrective rounds, most recently R22's
storage-probe-trigger reliability fix.

### S7.2 — First-Boot Provisioning *(complete)*

Applies the desktop/hardware/dev/AI/cyber/veil/focus profile resources
S7.0 merely embeds on media into a freshly-installed target system.
Implemented as a real transactional `serein.firstboot` module
(state machine, single-owner locking, idempotent retry, real S1
desktop verify+record and S2 hardware apply steps) as part of the
Phase 7 completion program - see `docs/firstboot/architecture.md` and
[ADR-0032](adr/0032-phase-7-completion-strategy.md).

### S7.3 — Recovery / Repair / Fallback *(complete, narrower scope than originally sketched)*

Managed-file integrity checking, diagnostics, planning, and repair
(`serein.recovery`) - see `docs/recovery/architecture.md` for why this
round's scope is narrower than "recovery partition/factory-reset":
firstboot-transaction recovery and Focus-transition recovery already
have real recovery mechanics built directly into their own
subsystems, so a separate layer was never needed for those.

## S8 — Refinement & Benchmarking

Apply Integrate → Measure → Replace retroactively across the whole stack:
benchmark first, replace an upstream component only where measurement
shows a demonstrated need. This phase never front-loads into earlier
phases — no component in S0–S7 should be replaced pre-emptively.

## Architecture invariant across all phases

> Serein integrates mature upstream components first, measures their
> behavior, and only replaces them when there is a demonstrated reason.

Every phase above is expected to honor this, not just S8.
