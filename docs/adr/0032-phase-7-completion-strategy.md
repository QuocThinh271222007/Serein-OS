# ADR-0032: Phase 7 completion strategy

## Status

Accepted.

## Context

The original roadmap defined S7.0 (Bootable ISO Prototype), S7.1
(Installer Integration), S7.2 (First-Boot Provisioning), and S7.3
(Recovery/Repair/Fallback) as sequential phases. S7.0 and S7.1 closed
through many real, evidence-driven corrective rounds (culminating in
S7.1R22's storage-trigger reliability fix). A parallel S7.2 branch
(`feat/serein-s7-2-firstboot-provisioning`) built a real transactional
first-boot module, forked from an earlier point in S7.1's own history.

Continued S7.1 corrective work repeatedly hit WSL/QEMU/TCG host-memory
infrastructure limits - real, but ultimately about this particular
development host, not about Serein's own correctness. Spending further
cycles chasing VM-only timing pathology stopped being the highest-value
use of effort once S7.1's actual installer safety invariants were
already proven through many real runs.

## Decision

Unify the remaining Phase 7 work (first-boot completion, identity/
branding, boot theming, recovery, update infrastructure) into one
integrated program on a single branch
(`feat/serein-s7-completion`), branched from S7.1's exact final head,
with the historical S7.2 firstboot branch reconciled onto it rather
than continued separately.

- **S1-S6.5 are reused, never redesigned.** Every new executor in this
  program (`serein.hardware.executor`, `serein.focus.runtime`,
  first-boot's own steps) consumes an existing S1-S6.5 planning
  function unchanged and only ever adds the apply/verify/record layer
  those planning functions were always designed to be consumed by.
- **Physical hardware becomes the primary final runtime gate**, not
  another WSL/TCG campaign. `NO_HEAVY_VM_CLOSURE_REQUIREMENT` -
  deterministic/unit/integration tests plus small, real, non-
  destructive command-level smoke checks (e.g. this program's own
  real GPG signing round-trip, the shell prompt's real bash execution)
  replace prolonged QEMU runs as this program's own quality gate.
- **GitHub-hosted CI is supplementary**, not required, while its
  infrastructure/billing availability is uncertain - re-run when
  convenient, never blocking.
- **Update/release infrastructure was pulled into late Phase 7**,
  earlier than originally scoped, because an installed Serein system
  must be maintainable without re-downloading a full ISO for every
  change - Section 42's own reasoning. Backed by the real Debian/APT
  ecosystem throughout, never a custom package manager.
- **Historical numbering is preserved, not silently redefined.**
  S7.2 originally meant First-Boot Provisioning; S7.3 originally meant
  Recovery/Repair/Fallback. Both scopes are completed here, alongside
  additional work (identity, boot theming, update infrastructure) the
  original numbering never separately named - documented as an
  expansion of Phase 7's completion program, not a silent rewrite of
  what S7.2/S7.3 always meant.

## Consequences

- Every new subsystem this program adds ships with real, passing
  tests at the exact commit this ADR lands in - never "architecture
  only" where a real, verifiable implementation was actually
  achievable in scope (the signed-repository GPG round-trip and the
  shell prompt's real bash execution are the clearest examples: both
  are genuinely run, not merely reviewed by hand).
- Where a real external dependency made genuine runtime verification
  impossible in this environment (Fastfetch, Plymouth, GRUB - none of
  which are installed here), that limitation is documented explicitly
  per-module rather than glossed over, mirroring this project's own
  established `systemd-analyze`-unavailable precedent from the
  original S7.2 work.
- `PHYSICAL_VALIDATION=DEFERRED` remains the honest state until a
  dedicated external-disk run actually happens - this ADR does not,
  and cannot, close that gap by itself.
