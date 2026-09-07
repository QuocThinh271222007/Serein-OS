# ADR-0020: Full Kali Environments and Untrusted/Malicious Workloads Require a VM Boundary

## Status

Accepted

## Context

Two related but distinct workloads need a hard isolation boundary
stronger than the rootless Distrobox/Podman toolbox (ADR-0018) can
provide: (1) a full Kali-style environment, whose sheer tool volume,
rolling-release churn, and network-/privilege-heavy default tooling
make it a poor fit for a shared-kernel container even setting aside
trust; and (2) genuinely untrusted or suspected-malicious binaries,
kernel exploit labs, and network-isolation experiments, where the
threat model specifically includes hostile code attacking the isolation
mechanism itself — something a container's shared host kernel cannot
defend against the way a VM's hardware-virtualization boundary can.

## Decision

- Kali is documented as a VM target, never a default host or toolbox
  base image (ADR-0018 already establishes Ubuntu/Debian as the
  toolbox default for this same reason).
- Untrusted/malicious binaries, kernel exploit labs, and
  network-isolation experiments are explicitly documented as requiring
  a VM boundary — container isolation, including Serein's own isolated
  toolbox, is stated plainly as **not sufficient** for hostile
  kernel/userspace samples. This is not a vague caveat; it is a
  concrete, testable plan action (`vm.isolation_policy`, always `NOOP`,
  `report_only`, mirroring S4's `voice.workload_note` pattern) so the
  policy is verifiable against real `serein cyber plan` output.
- VM prerequisite detection (`/dev/kvm`, kernel module, `qemu`,
  `libvirt`, a read-only user-access check) is read-only. S5 never
  starts `libvirtd`, never creates a VM, never downloads a Kali ISO or
  verifies its checksum, and never modifies a user's `kvm`/`libvirt`
  group membership. VM *creation* is explicitly out of scope for S5 —
  a future S7/S8 concern.
- "VM usable" is never inferred from a single binary: `qemu` alone,
  without a present `/dev/kvm` device, confirmed module, and confirmed
  user access, must never report `usable=True`
  (`tests/test_cyber.py::TestCapabilities::test_vm_isolation_usable_requires_full_chain`).

## Consequences

- A user who wants full Kali or needs to analyze a suspicious binary
  gets a clear, honest answer about *where* that belongs, instead of
  Serein quietly attempting it in an under-isolated container.
- No VM is ever created by this codebase, so there is no VM lifecycle,
  no ISO supply-chain risk, and no libvirt-group privilege question for
  S5 to have gotten wrong — all deferred cleanly to whichever future
  phase actually implements VM creation.
- The malware-analysis-requires-VM policy is machine-checkable (a real
  plan action with a fixed id and status), not something that can
  silently drift out of the documentation without a test noticing.

## Alternatives considered

**Treating the Distrobox/Podman toolbox as "isolated enough" for
malware analysis.** Rejected outright — this is the specific
misrepresentation Section 20 forbids; container isolation shares a
kernel with the host and is not a hostile-code sandbox.

**Implementing Kali-toolbox support as an optional Distrobox image in
S5.** Deferred, not rejected — Section 30 allows documenting this as a
future, explicitly non-default option, but S5 does not implement or
validate it now; doing so without evidence of real demand and without
resolving the rolling-release dependency-churn question would be
premature.
