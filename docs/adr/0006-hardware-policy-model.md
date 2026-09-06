# ADR-0006: Hardware Policy Model — Probe / Capabilities / Plan

## Status

Accepted. Reviewed during S2R (a live-validation corrective pass, see
`docs/validation/s2r/`) — the three-layer architecture itself held up;
S2R's five fixes (ZRAM syntax/detection, GPU classification confidence,
removed speculative NVMe tuning) were all corrections *within* this
model (mostly in the `*_policy.py`/`planner.py`/`capabilities.py`
layers), not changes to the model's shape.

## Context

S0 established a read-only hardware *probe* (`serein hardware probe`) —
useful for "what hardware exists," but silent on two other questions S2
needs to answer: "what can Serein safely control here" (a WSL guest and a
bare-metal desktop can report the same probe data yet have completely
different answers), and "given a workload profile, what would Serein
actually do." A single, monolithic "hardware manager" module could answer
all three, but would conflate detection, permission/ownership reasoning,
and workload-specific policy into one place — exactly the kind of
undifferentiated complexity the S1 desktop layer's "installed vs. running
vs. managed" split was designed to avoid.

## Decision

Three distinct, separately-testable layers, each its own CLI surface:

1. **Probe** (S0, unchanged) — hardware existence.
2. **Capabilities** (`capabilities.py`) — control feasibility, gated by
   environment (WSL/container guards) independently of any workload.
3. **Plan** (`planner.py`) — workload-specific policy, consuming
   capabilities/probes as inputs, producing an explicit, typed
   `PlanAction` list with no hidden state.

None of the three ever mutates the host. `capabilities.py` and
`planner.py` both call the same underlying `*_policy.py` detectors
(`cpu_policy.py`, `memory_policy.py`, etc.) rather than duplicating
detection logic — the layering is about *interpretation*, not
re-detection.

## Consequences

- Adding a sixth hardware profile in a later phase means writing one new
  set of planner functions against already-existing capability data — not
  touching detection code at all.
- A capability that later needs to change its virtualization-awareness
  logic (e.g. if a future WSL version exposes real cpufreq control) is a
  one-place fix in `capabilities.py`/`planner.py`'s shared `_virtualized()`
  helpers, not a scattered set of per-profile special cases.
- The three-layer split adds a small amount of indirection for what is,
  today, a fairly small rule set — an accepted cost for the clarity and
  testability gained, consistent with the layering S1 already validated.

## Alternatives considered

**A single `hardware_manager.py` with everything inline.** Rejected:
would make it harder to test "does the WSL guard work" independently of
"does the AI profile's EPP choice work," and would tempt future profile
logic to reach directly into raw sysfs reads instead of going through the
capability/policy abstraction — eroding the same discipline that keeps
S0/S1's detectors simple and independently testable.

**Extending `HardwareReport`/`hardware-report.schema.json` directly with
all the new S2 fields.** Rejected per the explicit S2 requirement that
`serein hardware probe` remain backward-compatible — bolting capability/
policy semantics onto the existence-only report would also conflate two
different questions ("does an EPP knob exist" vs. "should Serein touch
it") into one schema.
