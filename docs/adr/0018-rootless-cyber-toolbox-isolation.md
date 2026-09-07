# ADR-0018: Rootless Cyber Toolbox Isolation (Distrobox + Podman, no privileged defaults)

## Status

Accepted

## Context

ADR-0011 (S3) already chose Podman as Serein's default container
engine, rootless by default, paired with Distrobox. S5's Isolated Cyber
Toolbox needs the same engine — reusing it, not standing up a second
container framework — but cyber tooling raises the isolation-privilege
question sharply: many recon/exploit/wireless tools *want* raw sockets,
host networking, or device access, which is exactly the kind of default
privilege expansion the S5 brief forbids (Sections 32-33).

## Decision

- The toolbox reuses S3's Podman/Distrobox architecture verbatim
  (`serein.development.containers.detect_container_status`, not
  re-implemented).
- The default toolbox base image target is Ubuntu/Debian-based, not
  Kali (see ADR-0020 for why full Kali is VM-tier instead).
- No toolbox action ever plans `--privileged`, `--network=host`, a
  `/dev/...` device mount, or `CAP_SYS_ADMIN` as a default — enforced
  by `tests/test_cyber.py::TestForbiddenActions::test_no_privileged_container_defaults`.
  A tool category that genuinely needs one of these is represented as
  `BLOCKED`, pending explicit future user authorization, never silently
  granted.
- Serein does not assume a rootless container can perform every
  network-security task against host interfaces: packet capture on the
  host NIC, wireless monitor mode, and raw packet injection may
  genuinely require host- or VM-level access a rootless container
  cannot provide. This gap is documented (`docs/cyber/toolbox-strategy.md`),
  not hidden behind an optimistic default.

## Consequences

- The toolbox stays consistent with S3's own container posture —
  one engine, one set of conflict-detection rules, no duplicated
  Podman/Docker/Distrobox probing logic.
- Tools whose only viable operation mode requires elevated container
  privileges cannot be silently "made to work" by Serein defaulting to
  `--privileged` — a user who needs that must explicitly opt in later,
  outside what S5 plans by default.
- A future toolbox-creation Apply engine inherits an already-conservative
  privilege baseline instead of needing to retrofit one.

## Alternatives considered

**A separate, cyber-specific container engine/detection layer.**
Rejected: would duplicate S3's Podman/Docker/Distrobox detection for no
functional benefit, and risks the two layers reporting inconsistent
engine state.

**Defaulting risky tool categories to `--privileged` so "it just
works."** Rejected outright by the S5 brief itself (Section 32) — this
is precisely the silent-privilege-expansion pattern S5 must never
produce, even for tools that are individually low-risk to run once
already inside an isolated environment.
