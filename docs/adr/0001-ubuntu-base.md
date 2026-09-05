# ADR-0001: Ubuntu LTS as the Upstream Foundation

## Status

Accepted

## Context

Serein needs a base operating system to integrate with. Building an
independent Linux distribution (own package ecosystem, own kernel
maintenance, own release engineering) is a vastly larger undertaking than
building an integration/configuration layer on top of an existing,
well-maintained distribution.

## Decision

Serein targets **Ubuntu LTS** (currently Ubuntu 26.04 LTS, x86_64/amd64)
as its upstream foundation. Serein OS is an integration/distribution layer
over Ubuntu, not an independent Linux distribution with its own kernel or
package repository.

This means:

- Serein consumes Ubuntu's kernel, package manager (APT), and core system
  services as-is unless a specific, measured reason justifies a change
  (see [ADR-0002](0002-upstream-first.md)).
- Serein's own artifacts (the CLI, profiles, future ISO/installer) are
  layered on top of a standard Ubuntu install, not a replacement for one.

## Consequences

- Serein inherits Ubuntu's hardware support, security update cadence, and
  driver ecosystem, which would be infeasible to replicate independently.
- Serein is coupled to Ubuntu's release cycle and packaging decisions;
  significant upstream changes (e.g. packaging format shifts) can require
  Serein-side adaptation.
- ARM64 support is not precluded by this decision (Ubuntu supports it),
  but is out of scope until a later phase explicitly takes it on — see
  `docs/roadmap.md`.

## Alternatives considered

- **Independent distribution (own kernel/package ecosystem):** rejected —
  disproportionate maintenance burden for the problem Serein is actually
  solving (workstation integration, not distribution engineering).
- **Debian directly:** viable base but Ubuntu's broader hardware
  enablement (especially GPU/driver packaging) and LTS cadence better fit
  Serein's target audience (AI/dev/security workstation users) today.
- **Arch/rolling-release base:** rejected for S0 — a rolling base
  complicates the reproducibility goal in `principles.md`; may be
  revisited for a specific future variant if a measured need arises.
