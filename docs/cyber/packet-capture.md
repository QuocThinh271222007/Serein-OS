# Packet Capture: Tool Presence vs. Capture Privilege

## Two genuinely separate questions

`src/serein/cyber/capture.py` never infers capture *privilege* from
tool *presence*. Having `wireshark`/`tshark`/`dumpcap` installed proves
nothing about whether the current user can actually capture a packet —
that depends on `dumpcap`'s file capabilities (`cap_net_raw`/
`cap_net_admin`) or `wireshark`-group membership, neither of which
Serein ever grants automatically (Section 7).

`PacketCaptureStatus` keeps these as independent fields:

```python
wireshark: ToolStatus
tshark: ToolStatus
dumpcap: ToolStatus
capture_permitted: bool | None   # tri-state — see below
capture_permission_reason: str
```

## The sole evidence source: `dumpcap -D`

`dumpcap -D` lists capture-capable interfaces **without capturing a
single packet** — this is Wireshark's own documented safe way to check
capture rights. `_check_capture_permission()`'s logic:

| dumpcap installed | `dumpcap -D` result | `capture_permitted` |
|---|---|---|
| No | n/a | `None` — "nothing to evaluate" |
| Yes | returncode 0 | `True` — permitted |
| Yes | non-zero (permission denied) | `False` — not permitted |
| Yes | could not run / timed out | `None` — unknown |

This tri-state model is exhaustively unit-tested
(`tests/test_cyber.py::TestCapture`) and live-validated on Ubuntu 26.04
for the *installed-but-default-unprivileged* state (see
`docs/validation/s5/package-validation.md` Finding 3 —
a fresh, non-interactive `apt install tshark` leaves `dumpcap` with no
file capabilities and no `wireshark` group created). The "denied" real
runtime branch could not be reproduced in the WSL2 validation
environment (its default capability model is more permissive than a
real multi-user desktop session — see
`docs/validation/s5/known-blockers.md`), so that branch is verified by
unit test only.

## What Serein never does

- Never runs an actual capture (no `-i`/`-w` flag, ever, in production
  code or tests — enforced by `TestCapture::test_never_performs_a_live_capture`).
- Never lists real interface names/identifiers in `status`/`capabilities`
  JSON output — only the boolean outcome and a prose reason are kept
  (Section 53 — enforced by `TestPrivacy::test_status_never_leaks_interface_names`
  and `TestCapture::test_permission_check_never_lists_real_interfaces_in_status`).
- Never `chmod`s a capture device, never runs `setcap` on `dumpcap`,
  never adds the user to the `wireshark` group, never grants broad
  root. Live validation confirmed the default `apt install` state
  already leaves these ungranted — Serein has no reason, and no
  mechanism, to change that.

## Who owns the privilege decision

Granting non-root capture rights is a deliberate, user-facing decision
(`dpkg-reconfigure wireshark-common`, or manually setting `dumpcap`'s
capabilities/group) that requires an interactive prompt under a real
TTY on a real system — outside Serein's read-only detection scope
entirely, now and in any future Apply engine without an explicit,
separately-authorized step.
