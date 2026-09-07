# CPU / Memory / I/O — Implementation Notes

Companion to `docs/focus/resource-intent.md` (the conceptual model);
this page documents the concrete code shape.

## CPU/IO: `resources.build_resource_intents()`

One `ResourceIntent` per `(domain, resource)` for `resource in ("cpu",
"io")`, four domains -> 8 entries per policy. Each carries:

```python
ResourceIntent(
    resource="cpu" | "io",
    domain=role.domain,
    priority=role.state,                 # "primary" | "secondary" | "idle" | "off"
    relative_weight=RELATIVE_WEIGHTS[role.state] if role.state != "off" else None,
    mechanism="systemd CPUWeight (future) - ...",  # or IOWeight
    enforceable=False,
    confidence="low",
    reason=f"{domain} is {state} for this focus target; relative weight "
           "intent only, never enforced by S6.5 (no Apply engine exists).",
)
```

`relative_weight=None` for `"off"` domains - there is nothing to weigh
when a domain has no resource claim at all under this policy.

## Memory: `resources.build_memory_intent()`

A pure function of the domain roles plus `evidence.hardware.memory` -
only used to pick a `"medium"`/`"low"` confidence label (whether total
RAM was even detectable), never to compute a byte target.
`primary_target`/`secondary_target` derive from whether any domain
holds `primary`/`secondary` at all - `"none"` if not.
`reclaim_candidates` lists every `idle` domain by name.

## Verification commands (future, read-only)

Section 115 permits only safe, read-only future verification commands
in a plan's `verification` field once an Apply engine exists - e.g.
`systemctl show --property=CPUWeight <slice>`, `cat
/sys/fs/cgroup/.../memory.high`. S6.5 itself never runs any command
beyond what S2-S6's own detectors already run for their own evidence.

## Doctor checks touching this plane

`focus_system_reserve_present` (`doctor.py`) fails only if
`memory_intent.system_reserve` is empty for any target - a direct,
mechanical assertion that Section 64's "never 100% RAM/CPU as hard
ownership" invariant holds for every policy S6.5 can produce.
