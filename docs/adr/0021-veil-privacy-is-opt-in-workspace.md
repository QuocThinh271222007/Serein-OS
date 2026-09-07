# ADR-0021: Privacy Is an Opt-In Workspace, Never Global Routing

## Status

Accepted

## Context

A privacy-isolation subsystem could plausibly be designed either way:
route all host traffic through Tor by default once installed/enabled,
or require an explicit per-session activation. The former is simpler
to implement and matches some "privacy appliance" products, but it
directly contradicts Serein's broader design principle that Serein
integrates and configures upstream components without silently
changing a user's ordinary computing experience (S1-S5 never installed
a tool that changes default host behavior without an explicit,
inspectable plan action either).

## Decision

- Normal host networking, DNS, firewall rules, and proxy settings are
  never mutated by S6 - confirmed by direct regression tests scanning
  every plan action's text fields for forbidden phrases/markers
  (`tests/test_veil.py::TestInvariants`).
- Three explicit tiers exist: Normal Host (no Tor assumptions, no
  privacy claims), Veil Workspace (explicit activation, isolated
  routing), and Whonix (VM-level boundary) - see
  `docs/veil/architecture.md`.
- Installing the `tor` package itself is modeled as
  `recommended_tier="workspace"`, not `"host"` (`src/serein/veil/components.py`)
  - unlike S5's diagnostic host tools, the Tor daemon starts/enables
    itself by default on install, so it is deliberately kept out of any
    default host baseline.
- No `profiles/veil/` manifest is registered (Section 90) - a
  registered profile is exactly the kind of thing a hardware-policy
  selection could apply implicitly, which would itself violate this
  ADR.
- `serein veil plan`'s `workspace.routing` action explicitly documents
  that transparent proxying (`TransPort`/`DNSPort`/`iptables`/`nft`
  redirect) is not the default mechanism - the preferred boundary is
  application-level SOCKS5h or Tor Browser.

## Consequences

- A user must take a deliberate, inspectable step (a future Apply
  engine's explicit workspace activation) before any traffic is ever
  routed through Tor - there is no "install Tor and forget it, now
  everything is private" failure mode.
- Every capability's `usable` field can honestly report `None`/`False`
  without contradicting a background process the user did not ask for.
- A future Apply engine implementing real workspace activation has a
  clean, already-documented boundary to build against, rather than
  having to retrofit an opt-in model onto an opt-out default.

## Alternatives considered

**Global Tor routing once `tor` is installed and active.** Rejected -
directly contradicts the S6 brief's governing principle and would
silently change ordinary host networking behavior, which no other
Serein phase does either.

**A `veil` profile registered from S6's start, defaulting to
"disabled".** Rejected as unnecessary complexity: since S6 has no
Apply engine at all, a profile with no way to ever apply would only add
a confusing extra layer; `docs/architecture/profile-contract.md`
documents this explicitly.
