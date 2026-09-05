# Serein Architecture Principles

## Integrate → Measure → Replace

Serein prefers mature upstream Linux components first. A Serein-specific
replacement for an upstream component (a config generator, a service, a
tool) is only justified once:

1. The upstream component has been integrated and used as-is.
2. Its behavior has been measured against a concrete Serein requirement
   (performance, correctness, security posture, or user experience) and
   found insufficient.
3. The replacement's benefit is demonstrable, not assumed.

This rules out forking or reimplementing software "because we might need
it later." It also rules out large bundled toolsets (see
`security-model.md`) installed speculatively.

## Serein is an integration layer, not a distribution

Serein does not ship a kernel, a package manager, or its own package
repository. It targets Ubuntu LTS and orchestrates configuration on top of
it. See [ADR-0001](../adr/0001-ubuntu-base.md).

## Reproducibility and recoverability

Every mutating operation Serein will eventually perform must be:

- **Reproducible** — running it twice from the same inputs produces the
  same result.
- **Recoverable** — a failed or unwanted change can be diagnosed and, where
  practical, rolled back. See `installer-contract.md`.

No mutation is implemented in S0; this principle governs the contract that
future phases must satisfy.

## Explicit over implicit

- `declared` vs `implemented` vs `active` are always distinguished for
  profiles (`profile-contract.md`) — Serein never reports a capability as
  working when it is only planned.
- Diagnostics (`doctor-contract.md`) never fabricate a PASS.
- Hardware detection reports missing data as missing, never as a guess.

## Read-only by default

Every S0 command is read-only and requires no elevated privileges. Mutation
is deferred to later phases and, when introduced, must follow the
Discover → Resolve → Plan → Validate → Apply → Verify → Record lifecycle in
`installer-contract.md`.

## Workload isolation, not a security toolbox host

Serein's host is a trusted development/AI workstation. Cybersecurity
research and privacy-sensitive workflows are isolated into dedicated
environments (containers/VMs), not installed onto the host. See
`security-model.md` and [ADR-0004](../adr/0004-workload-isolation.md).
