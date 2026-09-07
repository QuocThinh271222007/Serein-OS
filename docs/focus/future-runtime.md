# Future Runtime Boundary

## Where S6.5 stops

```
S6.5 (this phase)
contracts + evidence reuse + policy + resource intent + transition simulation

    v  (not implemented here)

Future Focus runtime
    systemd slices (serein.slice / serein-{ai,dev,cyber}.slice / serein-background.slice)
    cgroup v2 resource weighting (real CPUWeight/IOWeight/MemoryHigh writes)
    runtime-specific lifecycle adapters (start/stop/quiesce a known service safely)
    GPU backend adapters (vendor-specific, per Section 29-30's own limits)
    a transition executor (implements the full REQUEST->...->COMMIT FOCUS state machine)
    verification/rollback (confirm an action took effect; undo it safely if not)
```

## Future slice hierarchy (documented only, Section 73 - do not create units)

```
serein.slice
├── serein-ai.slice
├── serein-dev.slice
├── serein-cyber.slice
└── serein-background.slice
```

Private workloads would likely live inside a VM/isolation boundary
(Whonix, or a future Veil workspace boundary) rather than simply
another slice, since privacy correctness needs a stronger boundary
than a cgroup weight can provide.

## Root/privilege boundary a runtime would need (Section 74-75)

Most real cgroup/service/global-policy operations require either root
or a delegated user slice under systemd's user-session cgroup
management. A future runtime's own plan actions would need to declare
`requires_root` honestly per action - S6.5 never assumes rootless
mutation is possible, and this phase performs zero privileged
operations of any kind (no `sudo`, no root writes, no D-Bus mutation,
no `systemctl set-property`).

## Future transaction semantics (Section 114)

A future runtime should implement:

```
plan -> validate -> prepare -> apply -> verify -> rollback if needed -> commit active focus
```

S6.5's own data structures (`FocusPolicy`, `FocusTransitionPlan`,
`LifecycleIntent.reversible`/`.cost`) are designed to be consumable by
this future model without a breaking redesign - `reversible` and
`cost` already exist as fields precisely so a future executor has
somewhere to report them per-action, even though S6.5 itself never
populates them with anything but conservative defaults.

## What a runtime implementation is not

It is not a general-purpose Linux process scheduler replacement. It
does not claim to out-optimize the kernel's own CFS/EEVDF scheduler;
it only ever expresses *relative, systemd-native* preference during
contention, layered on top of the kernel's own scheduling decisions -
exactly the same posture S6.5's planning-only intent already takes,
just with the ability to actually write the weight.
