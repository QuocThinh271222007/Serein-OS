# Resource Intent Model

## Intent vs. observed state vs. enforcement

Every resource plane S6.5 models distinguishes three genuinely
separate things, never collapsed:

```
intent       - what Serein would prefer, computed from domain roles
observed     - what S2-S6 evidence actually shows exists right now
enforcement  - whether Serein can make the intent real (S6.5: never)
```

`enforceable` is `False` on essentially every `ResourceIntent`,
`MemoryBudgetIntent`, and `GPULeaseIntent` this phase produces - not a
bug, the entire point: S6.5 has no Apply engine.

## Resource precedence (Section 10)

```python
RESOURCE_PRECEDENCE = (
    "system_safety_thermal",
    "privacy_security_boundary",
    "os_desktop_survival_reserve",
    "primary_focus",
    "secondary_workloads",
    "idle_workloads",
    "background_optional_work",
)
```

User focus preference (tiers 4-7) never outranks tiers 1-3. `FOCUS=AI`
must never mean "give AI all RAM until the desktop OOMs" - the system
reserve, and any active privacy/security boundary, always come first.

## CPU/IO weight, not percentage (Section 19-22)

```python
RELATIVE_WEIGHTS = {"primary": 1000, "secondary": 300, "idle": 80, "off": 0}
```

`resources.build_resource_intents()` produces one `ResourceIntent` per
`(domain, resource)` pair for `cpu` and `io`. The weight is a
**systemd CPUWeight/IOWeight-style relative scheduling preference
during contention** - it is not a CPU percentage, not a hard quota,
and not a throughput reservation. `CPUWeight=1000 != "100% CPU"`; the
weights above are proportions relative to each other, not to any
absolute ceiling, and they never sum to 100 (they sum to 1380).

No `CPUQuota=` is ever proposed as default policy (Section 21) - a
hard quota can throttle a bursty workload in ways that hurt more than
help; S6.5 documents it only as a possible future *optional*
constraint, never the default mechanism. No CPU affinity mask is ever
proposed either (Section 22) - `cpu_affinity_intent` is deliberately
absent from the model entirely (not merely `None`), since pinning
requires real per-core/NUMA/cache-topology evidence S6.5 does not
collect; a future phase with that evidence could add it deliberately.

## Memory budget (Section 23-27)

```python
MemoryBudgetIntent(
    system_reserve="protected - ... never claimed by a focus domain ...",
    primary_target="high" | "medium" | "low" | "none",
    secondary_target="high" | "medium" | "low" | "none",
    reclaim_candidates=[...],           # domain names, qualitative only
    pressure_policy="existing-zram-swap-policy (unchanged by S6.5)",
    target_bytes=None,                   # ALWAYS None in S6.5
    mechanism="systemd MemoryHigh (future, soft pressure only)",
    enforceable=False,
)
```

`system_reserve` is present and non-empty in every policy S6.5 can
produce - no policy assigns 100% of detected RAM to a focus domain
(`tests/test_focus.py::TestMemoryModel::test_no_policy_assigns_all_ram`).
`target_bytes` is always `None` - without real, measured workload
requirements, Serein does not claim "AI needs exactly 18 GB"; the
qualitative `primary_target`/`secondary_target` labels are the honest
alternative to fake precision (Section 25).

**`MemoryHigh`, not `MemoryMax`** (Section 24): `MemoryHigh` is a soft
pressure signal a future runtime could use; `MemoryMax` creates a hard
boundary that can trigger workload failure/OOM, so it is never named
as the default mechanism anywhere in this codebase - regression-tested
directly (`tests/test_focus.py::TestMemoryModel::test_memorymax_never_the_default_mechanism`).

**ZRAM/swap policy is untouched** (Section 27): `pressure_policy` only
ever describes the *existing* S2 zram-generator/swap mechanism as
already configured - S6.5 never rewrites `zram-generator` config,
swap priorities, or swappiness.

## Memory reclaim candidates (Section 26)

`reclaim_candidates` names domains in an `idle` state (e.g. "cyber
(idle workload)") - it never claims memory *will* be reclaimed absent
a future lifecycle action, and it is never paired with a byte count.

## GPU lease intent (Section 29-35) - see `docs/focus/gpu-lease.md`

## Service/container/VM lifecycle (Section 36-40) - see `docs/focus/transition-model.md`

## I/O weight (Section 28)

Modeled identically to CPU weight - a relative `IOWeight`-style
preference, never an MB/s throughput guarantee. Same
`RELATIVE_WEIGHTS` table, same `enforceable=False`.
