# ADR-0026: Focus Is Planning-Only Before Runtime Enforcement

## Status

Accepted

## Context

Introducing a resource-preference concept could plausibly be built
either as "design the contract first, implement enforcement later" or
"implement a minimal enforcement mechanism alongside the contract to
prove it works end to end." Every prior Serein phase (S1-S6) already
established the former pattern - detection and planning ship first,
real mutation is a distinct, later, explicitly-scoped step (the S7
installer contract exists for exactly this reason). Focus resource
enforcement additionally touches systemd/cgroups, GPU vendor runtimes,
and service/container/VM lifecycle - each with real failure modes
(throttling a bursty workload, OOM-killing something via a hard
`MemoryMax`, stopping a service a user still needed) that deserve
dedicated design attention, not a rushed first pass bundled into the
same phase that defines the domain model.

## Decision

- S6.5 implements contract + evidence reuse + policy + resource intent
  + transition simulation only. No cgroup write, no systemd unit
  mutation, no service/container/VM start-stop, no GPU power-mode
  change, no CPU governor change, and no focus persistence exist
  anywhere in this codebase.
- Every `FocusPolicy`/`FocusTransitionPlan` carries an explicit
  `runtime_enforcement: False` field - no JSON or CLI output can be
  mistaken for "this already happened."
- `serein focus status`'s `applied_focus` is always `None` and `mode`
  is always `"planning_only"` - S6.5 never fabricates an active focus
  it cannot back with real persisted/applied state.
- No background daemon (`serein-focusd` or equivalent) exists - every
  CLI invocation recomputes everything from live evidence, stateless.
- `docs/focus/future-runtime.md` documents the intended eventual
  architecture (systemd slices, cgroup v2 weighting, lifecycle
  adapters, a transition executor with verify/rollback) without
  implementing any of it.

## Consequences

- A future runtime-enforcement phase can be reviewed and shipped on
  its own merits, with its own safety analysis, without the
  domain-model/policy contract needing to change underneath it -
  `FocusPolicy`/`LifecycleIntent` already carry the fields (
  `reversible`, `cost`) a future executor needs.
- No user of `serein focus plan`/`transition` can be misled into
  thinking a resource change has occurred; every output is honestly
  labeled as intent.
- The phase ships faster and with a much smaller blast radius - a bug
  in policy computation can, at worst, produce a wrong *description*,
  never a wrong *mutation*.

## Alternatives considered

**Ship a minimal cgroup-weight-only enforcement path alongside the
contract.** Rejected - even "just" CPUWeight touches systemd slice
delegation and root/privilege questions (Section 74-75) that deserve
their own scoped design pass, and mixing "define the model" with
"first real mutation" in one phase is exactly the pattern S1-S6 avoided
throughout.

**Skip `runtime_enforcement`/`applied_focus` fields entirely since
they're always a fixed value in this phase.** Rejected - the fields
cost nothing and make every payload self-describing; a consumer
reading `serein focus status` JSON out of context still cannot
misinterpret it.
