# Focus (S6.5) Architecture

## Governing principle

> Many domains may exist simultaneously, but Serein may have at most one
> PRIMARY FOCUS at any moment.

Formally: `0 <= count(PRIMARY_FOCUS) <= 1`. Equally important:
`PRIMARY != EXCLUSIVE` - a primary focus receives preferential resource
*intent*, not sole ownership of the machine. Other domains keep
running; ordinary applications (a browser, an editor, a terminal, a
desktop) are never implied to stop.

## The semantic layer

```
User intent
    v
Serein Focus Controller  (src/serein/focus/)
    v
Domain policy             (policy.py - build_focus_policy)
    v
Resource intent            (resources.py - CPU/IO/memory/GPU/lifecycle)
    v
[future] systemd / cgroups / runtimes / VM / containers
    v
Linux kernel scheduler
```

Linux understands processes, CPU/memory/I/O usage, and priority.
Serein additionally understands "this workload belongs to AI" / "the
user currently cares most about AI" - a layer of *meaning* the kernel
has no concept of. S6.5 formalizes that layer as data (`FocusPolicy`,
`FocusTransitionPlan`) computed by pure functions - it does not
implement the arrows below "Domain policy" yet.

## Scope: contract + detection reuse + policy + planning + simulation

S6.5 is **not** runtime resource mutation. No cgroup writes, no
service stopping, no model unloading, no VM start/stop, no CPU
governor changes, no GPU power-mode changes, no focus persistence, no
automatic focus switching, no background daemon. Every `FocusPolicy`/
`FocusTransitionPlan` carries `runtime_enforcement: False` explicitly -
no output can be mistaken for "this already happened."

## Canonical focus targets and domains

```python
FOCUS_TARGETS = ("balanced", "dev", "ai", "cyber", "private")
FOCUS_DOMAINS = ("dev", "ai", "cyber", "private")
```

`balanced` is a target, not a domain: it means "no professional domain
owns primary-focus preference" - `primary_domain=None`, never a fifth
domain competing for PRIMARY.

## Domain states

```python
DOMAIN_STATES = ("primary", "secondary", "idle", "off")
```

`SUSPENDED` is deliberately absent - S6.5 has no runtime layer to
observe actual process suspension, and exposing a state that implies
observed runtime fact (when none is observed) would be dishonest.

## The one-primary invariant

```
0 <= number_of_primary_domains <= 1
```

Enforced by construction in `policy.evaluate_domain_roles()`: for a
professional target, exactly the requested domain is `"primary"` and
the other three are assigned `secondary`/`idle`/`off` per the
canonical role table (`docs/focus/domain-model.md`); for `"balanced"`,
every domain is `secondary` or `off`, never `primary`. Directly
regression-tested (`tests/test_focus.py::TestOnePrimaryInvariant`) and
checked live by `serein focus doctor`'s `focus_one_primary_invariant`
check against every one of the five targets.

## No Apply engine

Required CLI is read-only/planning only:

```
serein focus status
serein focus domains
serein focus capabilities [--json]
serein focus plan <target> [--json]
serein focus transition --from X --to Y [--json]
serein focus doctor [--json]
```

No `serein focus apply`. No `serein focus <target>` that mutates. No
`serein focus switch`.

## Module structure

```
src/serein/focus/
├── models.py       - dataclasses only, no behavior
├── domains.py       - target/domain validation, canonical transition graph
├── evidence.py        - the one aggregator of S2-S6's own capability reports
├── policy.py            - domain readiness + role assignment + build_focus_policy()
├── resources.py           - CPU/IO/memory/GPU/lifecycle/conflict builders
├── capabilities.py         - `serein focus capabilities`
├── planner.py                - `serein focus plan <target>`
├── transition.py               - `serein focus transition --from X --to Y`
├── status.py                     - `serein focus status`
└── doctor.py                       - `serein focus doctor`
```

## Reuse, not reinvention (Section 11-15/87-88)

- S2 hardware: `serein.hardware.probe.probe_hardware`,
  `serein.hardware.capabilities.build_capabilities`,
  `serein.hardware.thermal.detect_thermal`,
  `serein.hardware.power_policy.detect_power_policy` - no second CPU/
  GPU/memory/thermal/power detector.
- S3 development: `serein.development.capabilities.build_development_capabilities`.
- S4 AI: `serein.ai.capabilities.build_ai_capabilities` (PyTorch/ROCm/
  CUDA/Ollama/llama.cpp evidence, never re-detected).
- S5 cyber: `serein.cyber.capabilities.build_cyber_capabilities`
  (container toolbox, VM isolation - no second Podman/Distrobox/KVM/
  QEMU/libvirt detector).
- S6 veil: `serein.veil.capabilities.build_veil_capabilities` (Tor,
  Tor Browser, private workspace, Whonix - no second Tor/Whonix
  detector).

`evidence.gather_focus_evidence()` is the single place all five are
called; every downstream module (`policy.py`, `resources.py`,
`capabilities.py`, `status.py`, `doctor.py`, `transition.py`) consumes
the resulting `FocusEvidence` snapshot rather than re-probing
independently - the same discipline that prevents the class of
divergence bug S5R/S6R had to correct after the fact in earlier
phases (Section 88).

## What "implemented" means at this phase

Domain readiness evaluation, one-primary role assignment, CPU/IO/
memory/GPU/lifecycle intent construction, conflict identification, and
deterministic transition simulation all work end to end and are
exhaustively unit-tested with injected evidence. **No cgroup, systemd
unit, service, container, VM, GPU, or power-profile mutation of any
kind exists anywhere in this subsystem.** See
`docs/focus/known-limitations.md` and `docs/focus/future-runtime.md`
for exactly what a future runtime phase would need to add.
