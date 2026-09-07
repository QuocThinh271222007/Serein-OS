# Transition Model

## `build_focus_transition(from_focus, to_focus, evidence)` — one canonical function

The single source of truth `serein focus transition` and `serein
focus doctor`'s `focus_transition_graph_complete` check both consume
(Section 89) - it computes two `FocusPolicy` snapshots via the exact
same `build_focus_policy()` every other surface uses, then reports the
delta. It never executes anything.

## The state machine, and where S6.5 stops (Section 52)

```
REQUEST -> OBSERVE -> PLAN -> CHECK CONSTRAINTS -> QUIESCE CANDIDATES
   -> RESOURCE REWEIGHT -> ACTIVATE TARGET CANDIDATES -> VERIFY -> COMMIT FOCUS
```

S6.5 implements REQUEST/OBSERVE/PLAN/CHECK CONSTRAINTS as one
deterministic computation (`build_focus_transition`) and stops there -
every later stage (QUIESCE CANDIDATES through COMMIT FOCUS) belongs to
a future runtime executor this phase does not implement (see
`docs/focus/future-runtime.md`).

## Same-focus transition (Section 57)

```python
build_focus_transition("ai", "ai", evidence)
```

always returns `status="NOOP"` with empty `resource_changes`/
`lifecycle_changes` - a deterministic short-circuit, never a fabricated
full transition plan comparing a policy to itself.

## Status values

```
NOOP        - from_focus == to_focus
BLOCKED     - the target's own policy readiness is "blocked"
PLANNABLE   - everything else
```

## What a transition plan reports

```python
FocusTransitionPlan(
    from_focus, to_focus, status,
    prerequisites,       # readiness caveats for the target, if any
    resource_changes,    # per-domain cpu/memory role deltas + any gpu delta
    lifecycle_changes,   # target policy's own APPLY-status lifecycle intents
    conflicts,            # target policy's own conflicts
    blockers,              # populated only when status == "BLOCKED"
    warnings,               # privacy-specific caveats when private is involved
    expected_ram_reclaim_bytes=None,     # ALWAYS None
    expected_vram_reclaim_bytes=None,    # ALWAYS None
    reclaim_confidence="unknown",         # ALWAYS "unknown"
    reversible=True,
    cost,                                  # highest lifecycle-intent cost, else "low"
    runtime_enforcement=False,
)
```

## Lifecycle target semantics (S6.5R/S6.5RM) - which targets can even reach an instance action

No current lifecycle target can reach an instance-level `target_intent`
(`QUIESCE_CANDIDATE`/`PRIORITY_CANDIDATE`/`RESOURCE_INCREASE_CANDIDATE`/
`RESOURCE_REDUCE_CANDIDATE`). `ai_runtime`, `cyber_toolbox`, `cyber_vm`,
and `whonix` are all mechanism-only targets today: S6.5 has no
instance-level detector for any of them (no `podman ps`, `virsh list`,
`ollama ps`, `pgrep`, `systemctl is-active`, or equivalent - Section 42),
so `instance_present`/`instance_running` stay `None` and `target_intent`
stays `KEEP` regardless of mechanism readiness or focus role. An earlier
S6.5 pass treated the AI runtime binary's own presence as the recognized
instance for `ai_runtime`; this was corrected (S6.5RM) - binary/tool
presence only ever proves a mechanism exists, never that a daemon is
running, a server process is up, a model is loaded, or any concrete
runtime instance exists:

```
ai_runtime     - binary installed        -> mechanism_available=True,
                                              instance_present=None -> always KEEP
cyber_toolbox  - engine+Distrobox present -> mechanism_available=True,
                                               instance_present=None -> always KEEP
cyber_vm       - KVM/QEMU/libvirt ready    -> mechanism_available=True,
                                               instance_present=None -> always KEEP
whonix         - VM privacy boundary ready  -> mechanism_available=True,
                                                instance_present=None -> always KEEP
                 (qcow2 artifacts present or not - never promoted to
                 instance_present, Section 8)
```

See `docs/focus/resource-intent.md`'s "Lifecycle: mechanism readiness ≠
instance existence" section for the full four-fact model
(`recognized_by_serein`/`mechanism_available`/`instance_present`/
`instance_running`/`managed_by_serein`).

## AI -> Cyber example

```
cpu:    ai primary -> idle,  cyber idle -> primary
memory: ai high -> low,      cyber low -> high
gpu:    "preferred"/ai -> "shared" (if a GPU is present) or unchanged (none present)
lifecycle: ai_runtime stays KEEP even if its runtime binary is installed;
           cyber_toolbox/cyber_vm also stay KEEP even if their mechanism
           is ready (Section 6-7/39-40 - mechanism readiness is never
           promoted to an instance action, ai_runtime included since
           S6.5RM)
```

## Cyber -> AI example

Exact mirror for CPU/memory: `cyber` role goes `primary -> idle`, `ai`
goes `idle -> primary`; `ai_runtime` stays `KEEP` even if its binary is
installed (S6.5RM - no instance evidence exists to promote it toward
`PRIORITY_CANDIDATE`). `cyber_toolbox`/`cyber_vm` also stay `KEEP`
regardless of mechanism readiness - there is no toolbox/VM instance
evidence to quiesce. `dev` remains `secondary` in both directions - it
is never involved in the ai/cyber IDLE-vs-PRIMARY swap.

## AI -> Private example (Section 55)

`build_focus_transition("ai", "private", evidence)` always adds two
warnings regardless of readiness:

> "Private focus preserves every S6 invariant regardless of this
> transition: no global Tor routing, no global DNS mutation, no direct
> Whonix-Workstation clearnet egress."

> "Any other domain's GPU/resource preference must never interfere
> with privacy isolation invariants."

If `private`'s own readiness is `"blocked"` (nothing installed at all)
the transition's `status` is `"BLOCKED"` and `blockers` names the exact
readiness reason. If readiness is `"limited"` (e.g. a usable Tor
*client* but no complete private-workspace/browser/Whonix boundary -
S6.5R Corrective D, `docs/focus/domain-model.md`), the transition stays
`"PLANNABLE"` with `prerequisites` naming the gap - Serein never
pretends a privacy focus is fully realizable from Tor client usability
alone, but a partial/limited state is still honestly reported as
plannable, not silently upgraded or downgraded (Section 32).

## Private -> AI example (Section 56)

Adds a distinct warning:

> "Leaving private focus does not automatically discard any active
> private workspace/session state - explicit lifecycle handling
> remains future work; S6.5 only reports this, it never destroys
> state."

No private-specific lifecycle action is ever proposed as `APPLY` for
this direction - S6.5 has no mechanism to know about, let alone
destroy, an active private session.

## Same-target NOOP coverage and the full canonical graph (Section 100)

`domains.CANONICAL_TRANSITIONS` enumerates every ordered pair among
the five targets (20 pairs); `serein focus doctor`'s
`focus_transition_graph_complete` check plans all 20 plus all 5
same-target NOOPs, asserting none raises. Every pair is also
individually parametrized in `tests/test_focus.py::TestTransitionPlanner`.

## Reversibility and cost (Section 115-117)

`reversible=True` on every S6.5 transition plan today - nothing has
actually happened, so nothing needs reversing; the field exists so a
future runtime executor's own transitions can report `False` when a
real action (e.g. a VM shutdown) genuinely isn't trivially reversible.
`cost` is a qualitative label (`low`/`medium`/`high`/`unknown`) derived
from the highest-cost lifecycle intent in the target policy - never a
fabricated time estimate (Section 116).

## User data safety (Section 117)

No transition ever proposes `delete`/`destroy`/`discard` for any
resource - "releasing" a resource always means quiesce/unload/stop
*candidate*, language enforced directly by regression
(`tests/test_focus.py::TestLifecycleIntents::test_never_deletes_or_destroys`).
