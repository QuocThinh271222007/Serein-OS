# Veil (S6) Architecture

## Governing principle

> Privacy is an explicit boundary, not an invisible global side effect.

And:

> Normal host networking must remain normal unless the user explicitly
> enters a privacy workspace.

Serein never boots into a state where all traffic silently routes
through Tor, and never claims `private=true`/`anonymous=true` from
partial evidence. Every module in `src/serein/veil/` is designed around
that constraint first, tool coverage second.

## Three tiers

```
Normal Host          - ordinary networking, no Tor assumptions, no privacy claims
Veil Private Workspace - explicit activation, isolated browser/profile,
                          Tor egress, DNS-leak protection, kill-switch
                          semantics, minimal host integration
Whonix Boundary        - Gateway VM + Workstation VM, the strongest
                          supported Serein privacy boundary
```

`VEIL_TIERS = ("host", "workspace", "vm", "user-managed")` in
`src/serein/veil/models.py` - a deliberately separate vocabulary from
S5 cyber's `("host", "toolbox", "vm", "user-managed")` (Section 86):
Veil's "workspace" tier does not mean "safe to have on the daily host
by default" the way S5's "host" tier does - installing the Debian/
Ubuntu `tor` package starts and enables a system-wide `tor.service` by
default, so every Tor-related component (`tor`, `torsocks`, `nyx`,
`obfs4proxy`, `tor-browser`) is `recommended_tier="workspace"`, never
`"host"` (see `docs/veil/tor-strategy.md`).

## No Apply engine, no profile

S6 implements `detect`/`status`/`capabilities`/`doctor`/`plan` only
(Section 5) - no `serein veil apply` exists, and nothing here writes a
package, starts a service, mutates `torrc`, creates a network
namespace, creates/imports a VM, or downloads anything (a Tor Browser
bundle or a Whonix image alike).

Unlike S2-S5, **no `profiles/veil/` manifest is registered** (Section
90) - a registered profile is exactly the kind of thing Serein's
hardware-policy layer could apply as part of a normal profile
selection, which would cut directly against "privacy is opt-in, never
an invisible global side effect." `serein veil status`/`capabilities`/
`plan`/`doctor` all work standalone, with no profile dependency. See
`docs/architecture/profile-contract.md`.

## Module structure

```
src/serein/veil/
├── models.py         - dataclasses only, no behavior
├── tor.py             - Tor client package/service/config/SOCKS evidence
├── browser.py         - Tor Browser (torbrowser-launcher) + ordinary browser
├── dns.py              - DNS-leak model (never inferred from Tor alone)
├── workspace.py        - private-workspace readiness + kill-switch model
├── whonix.py            - Whonix Gateway/Workstation capability (reuses S5 VM readiness)
├── components.py        - declarative privacy-component manifest
├── capabilities.py      - `serein veil capabilities`
├── planner.py            - `serein veil plan [tor|workspace|whonix]`
├── status.py             - `serein veil status`
└── doctor.py              - `serein veil doctor`
```

## Reuse, not reinvention (Section 88)

- `serein.development.runner.CommandRunner` - the same injectable,
  read-only command execution S3-S5 use; no second subprocess
  framework.
- `serein.development.dpkg.apt_package_installed` - the same
  dpkg-query-based package-installation probe S3/S5R use.
- `serein.development.toolchains.probe_tool` - the same `--version`
  probing helper every subsystem uses.
- `serein.development._util.default_home`/`marker_exists` - the same
  injectable-home marker-check helpers S3's `python.py`/`node.py`/
  `editor.py` use, reused directly for Whonix image-presence detection.
- `serein.cyber.virtualization.detect_vm_status`/`evaluate_vm_readiness`
  - Whonix's VM backend readiness is S5's `VMReadiness` verdict,
  consumed as-is (Section 27) - no second KVM/QEMU/libvirt detector.
- `serein.hardware.environment.detect_environment` - the same
  WSL/container/hypervisor detection S2-S5 use.
- `serein.doctor.models` - the same PASS/WARN/FAIL/SKIP model every
  subsystem's doctor uses.

## What "implemented" means at this phase

Detection, capability modeling (installed-vs-usable, tier-vs-default,
tor-vs-DNS-vs-workspace-vs-Whonix all kept genuinely separate), and
`serein veil plan` all work end to end and are exhaustively unit-tested
with injected runners/roots/homes. **No Tor daemon is ever started, no
system DNS/firewall/proxy is ever mutated, no Tor Browser or Whonix
image is ever downloaded, no browser profile is ever created, no
network namespace/container/VM is ever created, and no external
network probe (a Tor connectivity check, a public-IP lookup) is ever
performed.** See `docs/veil/known-limitations.md` for exactly what a
future phase would need to add.
