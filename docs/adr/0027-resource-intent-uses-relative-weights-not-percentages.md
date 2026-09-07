# ADR-0027: Resource Intent Uses Relative Weights, Not Fake Percentages

## Status

Accepted

## Context

A naive resource-preference model could assign fixed percentages
("AI = 70% CPU, Dev = 20%, System = 10%") - intuitive to read, but
factually wrong for how Linux actually schedules CPU/I/O: cgroups v2's
`CPUWeight`/`IOWeight` are *relative scheduling preferences during
contention*, not reservations, and Linux provides no mechanism that
guarantees a process group a fixed percentage of CPU time the way the
naive model implies. Presenting fabricated percentages would actively
mislead a reader about what the mechanism can and cannot do, and would
set an expectation a future runtime could never actually satisfy.

## Decision

- CPU and I/O intent are expressed as relative weights matching
  systemd's own `CPUWeight`/`IOWeight` concept:
  `{"primary": 1000, "secondary": 300, "idle": 80, "off": 0}` - chosen
  to sum to a number that is deliberately *not* 100
  (`tests/test_focus.py::TestFocusConstants::test_relative_weights_are_not_percentages`
  asserts this directly), so no reader can mistake the numbers for
  percentages.
- Every `ResourceIntent`'s `mechanism` field states explicitly that the
  weight is relative, never a percentage or quota - and `docs/focus/
  resource-intent.md`/`cpu-memory-io.md` explain the distinction in
  prose.
- No hard `CPUQuota=` is proposed as default policy (a hard quota can
  throttle bursty workloads counterproductively); it is documented only
  as a possible *future optional* constraint.
- No CPU affinity mask is ever proposed by default - pinning requires
  real per-core/NUMA/cache-topology evidence this phase does not
  collect, so `cpu_affinity_intent` is absent from the model entirely
  rather than present-but-null.
- Memory intent follows the same discipline: `target_bytes` is always
  `None` unless real, measured workload evidence exists; qualitative
  `"high"/"medium"/"low"` labels are preferred over invented precision.

## Consequences

- Every number this subsystem produces is honestly interpretable by
  anyone who understands what `CPUWeight` actually does - no reader is
  set up to expect a guarantee Linux cannot provide.
- A future runtime that actually writes these weights inherits a
  model that is already technically accurate, rather than needing a
  breaking redesign to correct a percentage-based misconception once
  real cgroup writes are added.
- `serein focus doctor`'s determinism/no-fabrication checks stay easy
  to write, since "is this a real weight or an invented percentage" is
  a simple, mechanical distinction to test for.

## Alternatives considered

**Percentage-based intent with a disclaimer in the docs.** Rejected -
a disclaimer buried in documentation does not prevent a CLI user from
reading `AI: 70%` and reasonably assuming a guarantee; the wrong
mental model would spread regardless of what the docs said.

**Omit numeric weights entirely, use only qualitative labels
(high/medium/low/none) for CPU/IO too.** Considered, but relative
weights are directly meaningful once mapped to the real systemd
mechanism they represent (Section 19's own worked example already
uses numbers: `primary=1000, secondary=300, idle=80, background=20`),
so keeping them - clearly labeled as relative, never percentage - was
judged more useful than only qualitative labels, while memory (where
no equally standard numeric convention exists yet) stays qualitative.
