# ADR-0019: Packet Capture Privilege Ownership (dumpcap -D as sole evidence, never granted automatically)

## Status

Accepted

## Context

Packet capture needs two genuinely separate facts: is capture tooling
*installed*, and can the current user actually *capture*. Collapsing
these (as many naive tools do — "wireshark is installed, so capture
must work") is both technically wrong (capture rights are a distinct,
separately-granted privilege) and operationally dangerous for an
OS-integration tool to assume, since the fix for "capture doesn't work"
is often "grant broad `CAP_NET_RAW`/`CAP_NET_ADMIN` to a binary or add
a user to a capture group" — exactly the kind of privilege grant the S5
brief forbids Serein from performing automatically (Section 8).

## Decision

- `capture_permitted: bool | None` is modeled as a field fully
  independent of `wireshark`/`tshark`/`dumpcap` installation state.
- The sole evidence source is `dumpcap -D` — Wireshark's own documented
  safe way to check capture rights, since it lists capture-capable
  interfaces without capturing a single packet. Returncode 0 → `True`;
  non-zero (permission denied) → `False`; the command not installed or
  not runnable → `None` ("unknown"), never guessed either way.
- Real interface names/identifiers surfaced by `dumpcap -D` are never
  exposed in `status`/`capabilities` JSON output — only the boolean
  outcome and a prose reason are kept (Section 53).
- Serein never `chmod`s a capture device, never runs `setcap` on
  `dumpcap`, never adds a user to a capture-privileged group, and never
  runs an actual capture (no `-i`/`-w` flag anywhere in this codebase).
- Live validation on Ubuntu 26.04 confirmed the default state after a
  plain `apt install tshark`: no file capability set on `dumpcap`, no
  `wireshark` group created — granting capture rights is a distinct,
  interactive (`dpkg-reconfigure wireshark-common`) step Serein
  deliberately never performs.

## Consequences

- A user gets an honest, three-state answer ("permitted" / "denied" /
  "unknown") instead of a false-positive "capture works" claim derived
  from tool presence alone.
- The "denied" branch is unit-tested but could not be reproduced live
  in the WSL2 validation environment (its default capability model
  differs from a real multi-user desktop) — documented honestly in
  `docs/validation/s5/known-blockers.md` rather than faked.
- A future Apply engine that wants to *grant* capture rights has a
  clearly-scoped, separate decision to make — this ADR does not
  pre-authorize it.

## Alternatives considered

**Inferring capture permission from `wireshark`/`tshark` installation
alone.** Rejected: technically wrong, and the exact anti-pattern
Section 8 calls out by name.

**Checking group membership (`id` output) instead of running
`dumpcap -D`.** Rejected as the *sole* signal: group membership alone
doesn't account for file-capability-based grants (`cap_net_raw` set
directly on the binary without any group involved), so it would produce
false negatives; `dumpcap -D` is the mechanism Wireshark's own docs
recommend precisely because it reflects the actual runtime outcome
regardless of which grant mechanism was used.

**Running an actual short capture to "really" confirm.** Rejected
outright — this is a real capture, forbidden by Section 8 regardless of
duration or target.
