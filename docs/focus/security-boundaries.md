# Focus Security Boundaries

## Focus never weakens an earlier phase's invariants (Section 93)

S6.5 sits *above* S2-S6, translating their own evidence into resource
intent - it never introduces a new privilege, a new network exception,
or a new isolation bypass. Every claim below is enforced by a direct
regression in `tests/test_focus.py::TestSecurityInvariants` scanning
the relevant `FocusPolicy`'s full JSON output for forbidden phrases.

## AI focus cannot disable S5 isolation

`build_focus_policy("ai", evidence)`'s output never contains
`--privileged` or "disable isolation" - AI becoming primary changes
CPU/memory/GPU *intent* only; it has no path to any S5 cyber-toolbox
privilege setting.

## Cyber focus cannot add privileged container access

Even with `cyber` as the primary focus (and its own lifecycle intents
naming the S5 toolbox/VM as priority candidates), the policy text never
contains `--privileged` or `CAP_SYS_ADMIN` - S6.5 only ever plans a
priority/quiesce *candidate* for an already-existing S5 capability; it
never proposes a new privilege grant. S5's own "never `--privileged`,
never `--network=host` by default" invariant
(`docs/cyber/toolbox-strategy.md`) is untouched.

## Cyber focus cannot imply host networking

Same mechanism: no `network=host`/`--network=host` string ever appears
in a cyber-focused policy.

## Private focus cannot globally route the host through Tor

`build_focus_policy("private", evidence)`'s output never contains
"route entire host" or "global tor routing" - S6's own Section 1/3
invariant ("normal host networking remains normal unless the user
explicitly enters a privacy workspace") is inherited unchanged; S6.5
adds resource-preference intent on top of it, never a routing change.

## Private focus cannot weaken Whonix topology

No "direct clearnet" phrase ever appears in a private-focused policy -
ADR-0024's Whonix-Workstation-never-direct-clearnet-egress invariant
is untouched; S6.5 never touches VM network topology at all.

## Dev focus cannot disable security controls

No "disable security"/"disable mitigations" phrase ever appears in a
dev-focused policy - development tooling preference has no path to
kernel mitigation flags or security-control toggles.

## No focus bypasses thermal safety

No "override thermal"/"bypass thermal" phrase ever appears in any
policy - see `docs/focus/constraints.md`.

## Doctor enforcement

`serein focus doctor`'s `focus_private_preserves_veil_invariants` and
`focus_plan_no_mutation` checks make a subset of these assertions live
against every focus target on every run, not merely in unit tests -
a FAIL here is one of the few genuine structural defects this doctor
recognizes (Section 92).
