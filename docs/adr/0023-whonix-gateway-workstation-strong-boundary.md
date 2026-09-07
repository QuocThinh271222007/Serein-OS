# ADR-0023: Whonix Gateway/Workstation as the Strong Privacy Boundary

## Status

Accepted

## Context

S5 already established that container isolation (rootless Podman +
Distrobox) is insufficient for hostile kernel/userspace samples - full
Kali environments, untrusted binaries, and kernel-exploit labs all
require a VM boundary (`docs/cyber/vm-isolation.md`, ADR-0020). Privacy
isolation has an analogous but distinct requirement: an ordinary
container shares the host kernel and can inherit DNS behavior, host
services, metadata, filesystem integration, clipboard, and display/
session integration (Section 14) - none of which is acceptable for the
strongest privacy tier. Whonix's own two-VM architecture (a Gateway
that owns all Tor connectivity, and a Workstation that can only reach
the network through the Gateway) is the established, audited approach
for exactly this problem.

## Decision

- Whonix is modeled as Gateway + Workstation, never a single generic
  VM (`WhonixCapabilityInfo` keeps `gateway_image_present`/
  `workstation_image_present` as independent fields).
- Whonix's VM-backend readiness reuses S5's `evaluate_vm_readiness()`
  directly (`serein.cyber.virtualization`) - no second KVM/QEMU/libvirt
  detector exists in this codebase (Section 27).
- Distrobox/an ordinary container is explicitly documented as *not*
  the strongest privacy boundary Serein offers, mirroring the
  malware-analysis reasoning already accepted for S5
  (`docs/veil/private-workspace.md`).
- Image presence is checked only at the exact official install path
  Whonix's own KVM documentation specifies
  (`~/.local/share/images/Whonix-{Gateway,Workstation}.qcow2`) - never
  a filesystem-wide search, and a matching filename is never trusted as
  a genuine, verified image (Section 29/31) - `usable` stays `None`
  even with both images present, since Serein never checks the
  signature/hash Whonix's own docs describe.
- No download, import, or VM creation exists anywhere in this
  subsystem (Section 30) - confirmed by regression
  (`tests/test_veil.py::TestWhonix::test_never_creates_or_imports_a_vm`).

## Consequences

- Serein never overstates Whonix readiness from partial evidence (VM
  backend ready but images missing, or images present but unverified)
  - each state gets its own honest `usable=False`/`None` outcome
    (`docs/veil/whonix.md`).
- A future provisioning phase inherits a clear, already-tested contract
  for what "ready" means at each layer (hardware, access, packages,
  images, verification, topology) rather than needing to invent one
  under time pressure.
- Whonix remains explicitly the *strongest* tier, not the default -
  `docs/veil/private-workspace.md`'s tier model keeps `tor_application`
  and `isolated_workspace` as intermediate options that do not require
  a VM at all.

## Alternatives considered

**Model Whonix as one generic "privacy VM" without distinguishing
Gateway/Workstation.** Rejected - loses the specific topology
invariant (ADR-0024) that makes Whonix's design meaningfully stronger
than a single VM with a Tor client installed inside it.

**Trust a `Whonix-*.qcow2` filename anywhere on disk as sufficient
evidence.** Rejected outright per Section 31 - filename matching proves
nothing about provenance or integrity; a compromised or corrupted image
would pass this check trivially.
