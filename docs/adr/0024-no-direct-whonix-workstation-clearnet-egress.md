# ADR-0024: No Direct Whonix-Workstation Clearnet Egress

## Status

Accepted

## Context

Whonix's entire security model depends on Whonix-Workstation having no
network path to the internet except through Whonix-Gateway. If a future
provisioning phase ever gave Workstation its own direct (bridged or
NAT'd-to-host) network adapter, Workstation's traffic could bypass Tor
entirely under a misconfiguration or a compromised Gateway - silently
defeating the entire point of running Whonix. Because Serein plans
component actions today that a future Apply engine will eventually
execute, this invariant needs to be encoded now, in the plan output
itself, not left to be "remembered" when that engine is built.

## Decision

- The canonical topology is fixed: Whonix-Workstation -> internal-only
  isolated virtual network -> Whonix-Gateway -> NAT/host uplink.
  Workstation never receives a direct host-network-facing adapter in
  this topology (Section 32-33/100).
- `src/serein/veil/planner.py`'s `whonix.network_topology` action
  encodes this directly in its machine-readable `tool` field
  ("internal-only Whonix-Workstation adapter (never direct clearnet
  egress)") and `reason` text, not only in prose documentation.
- A dedicated regression
  (`tests/test_veil.py::TestInvariants::test_whonix_workstation_never_planned_with_direct_clearnet_egress`)
  asserts the invariant statement is present in the action's fields and
  no bridged/direct-egress phrasing ever appears - this test would fail
  immediately if a future change accidentally proposed a topology that
  violated it.
- `docs/veil/whonix.md` and `docs/veil/host-integration.md` both
  document the invariant so it is discoverable without reading test
  code.

## Consequences

- A future Apply engine implementing real Whonix VM networking has a
  test that fails loudly if its generated libvirt network XML (or
  equivalent) ever gives Workstation a bridged/host-facing interface -
  the invariant is enforced by construction in the planning layer
  before any VM configuration code is written.
- `whonix.network_topology` currently only ever reaches `APPLY`
  (never executed) or `BLOCKED` - there is no path in today's code for
  it to represent a completed, incorrect topology, so this ADR is
  currently a forward-looking constraint rather than a live bug fix.
- Anyone reviewing a future PR that touches Whonix networking has a
  named ADR and a named test to check against, rather than needing to
  rediscover why the constraint exists.

## Alternatives considered

**Leave the invariant as prose-only documentation, encoded later when
an Apply engine exists.** Rejected - the S6 brief explicitly asks for a
machine-readable policy/test now (Section 33/100), and doing so is
cheap: the plan action's text fields already carry this information for
other purposes, so asserting on them costs nothing extra.

**Give Workstation a direct adapter but firewall it at the VM/host
level instead.** Rejected as a materially weaker design than Whonix's
own upstream-recommended topology - it reintroduces exactly the
misconfiguration risk (a firewall rule silently dropped/bypassed) that
routing Workstation's only path through Gateway avoids by construction.
