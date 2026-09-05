# ADR-0002: Upstream-First (Integrate → Measure → Replace)

## Status

Accepted

## Context

A workstation integration project can easily drift into reinventing
components upstream already provides well: init systems, network
management, display managers, package tooling. That drift produces a
larger, harder-to-maintain surface with no guaranteed benefit over the
upstream component it replaced.

## Decision

Serein follows **Integrate → Measure → Replace**:

1. Integrate the mature upstream component first, as-is.
2. Measure its behavior against a concrete Serein requirement.
3. Only replace or wrap it when the measurement shows a demonstrated,
   documented shortfall — and the replacement's benefit is itself
   measured, not assumed.

Concretely: no forking mature upstream software without demonstrated need;
no reimplementing a system service Serein could configure instead; no
premature replacement of default Ubuntu components (init, network stack,
display server) without a specific, measured reason recorded in an ADR.

## Consequences

- Slower to add "impressive" custom components, by design — the default
  answer to "should we build our own X" is "not yet."
- Every deviation from upstream defaults should be traceable to a
  measurement or a concrete documented requirement, not a preference.
- Keeps Serein's own maintenance surface (the actual code in this
  repository) small relative to the capability it delivers, since most
  capability comes from upstream.

## Alternatives considered

- **Build custom components proactively** ("we'll probably need our own
  X eventually"): rejected — violates the core principle and produces
  unmeasured, speculative complexity.
- **Never replace anything, ever:** also rejected — the principle
  explicitly allows replacement once justified; the point is ordering
  (measure before replace), not permanent upstream lock-in.
