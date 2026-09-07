# Kill Switch Semantics

## The invariant (Section 23)

If a privacy workspace ever claims "Tor-only", Tor failing must never
silently fall back to clearnet. Proving that guarantee requires
network-level enforcement (firewall rules, network-namespace routing
that has no default-allow path) - none of which S6 implements.

## Why this stays conceptual only

Section 59/103 forbid mutating `nftables`/`iptables`/`ufw`/`firewalld`
in this phase. Without a mutation mechanism, Serein cannot *configure*
a kill switch, only describe the requirement.
`src/serein/veil/workspace.py`'s `evaluate_kill_switch()` reflects
that honestly:

```python
KillSwitchStatus(
    available=True,      # a future mechanism Serein could plan
    configured=False,     # S6 never configures one - always False
    usable=None,           # never inferred from firewall package presence
)
```

`usable` is never derived from whether `nftables`/`iptables`/`ufw` is
merely *installed* (Section 58) - a firewall tool's presence proves
nothing about whether a Tor-only rule actually exists, so guessing from
it would be exactly the kind of false certainty this subsystem is
built to avoid everywhere else.

## What a future Apply engine would need

- A concrete enforcement mechanism (network namespace with no default
  route out, or firewall rules scoped to the workspace's own
  network namespace/cgroup - not the whole host).
- A verification step that can *prove* the rule exists and blocks
  outbound traffic when Tor is down, not just that a config file was
  written.
- Only then would `configured=True`/`usable=True` become legitimate to
  report - and even then, `serein doctor` would need a genuine FAIL
  path for "claims Tor-only but the enforcement is missing/broken"
  (Section 50) - a state S6 cannot currently produce at all, so no such
  FAIL condition exists yet (`doctor.py`'s
  `veil_tor_only_claim_kill_switch` check always PASSes today,
  explicitly documented as reserved for that future state).
