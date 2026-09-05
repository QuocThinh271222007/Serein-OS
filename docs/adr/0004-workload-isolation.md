# ADR-0004: Workload Isolation for Cybersecurity/Privacy/Untrusted Work

## Status

Accepted

## Context

Serein's stated scope includes cybersecurity research/authorized testing
and privacy-oriented workflows (Tor/Whonix-style), alongside normal
development and AI workloads on the same physical machine. Installing an
offensive-security toolset directly onto the host, or routing all host
traffic through Tor, would contaminate the host's package environment,
widen its attack surface, and conflict with its role as a stable daily
workstation.

## Decision

Cybersecurity and privacy/untrusted workloads are isolated from the
trusted host environment (containers or a dedicated VM), never installed
in bulk onto the host. Concretely:

- No large offensive-security tool bundle (e.g. a Kali-equivalent
  metapackage) is installed on the host.
- No mechanism routes all host network traffic through Tor; a privacy
  workflow is entered deliberately (a dedicated environment), not a
  standing host-wide state.
- Security/privacy tooling that later phases add (S5 Cybersecurity, S6
  Veil) targets isolated environments by construction, not as an
  afterthought bolted onto the host profile.

See `docs/architecture/security-model.md` for the target architecture
diagram.

## Consequences

- Host package churn stays low: the "core"/"dev"/"ai" profiles never pull
  in security-research tooling as a side effect.
- Security/privacy workflows carry the overhead of entering an isolated
  environment (container/VM startup) rather than being instantly
  available on the host. This is an accepted trade-off for containment.
- The `cyber` and future veil/privacy profiles (`profile-contract.md`) are
  declared with this isolation boundary as a design requirement from the
  start — when implemented, they must provision an isolated environment,
  not host packages.

## Alternatives considered

- **Install everything on the host ("Kali + desktop cosmetics + CUDA"):**
  explicitly rejected — this is called out as an anti-goal in Serein's
  project scope. It maximizes attack surface and package conflicts for
  marginal convenience.
- **Full host-wide Tor routing:** rejected — breaks normal workstation
  usability and offers a false sense of "always private" while making
  actual privacy workflows harder to reason about.
- **No isolation, rely on user discipline:** rejected — Serein's job is to
  make the safe default the easy path, not to require the user to
  manually sandbox risky work every time.
