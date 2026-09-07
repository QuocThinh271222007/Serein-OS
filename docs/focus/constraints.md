# Constraints: Thermal, Battery, Power Profile

## Thermal safety always wins (Section 61)

`resources.build_constraints()` reads S2's own thermal evidence
(`hardware.thermal.detect_thermal`, reused - never re-detected). If no
thermal telemetry is available, S6.5 never invents headroom:

> "Thermal telemetry is unavailable on this host - no thermal headroom
> is assumed or invented; kernel/hardware thermal protection is never
> overridden."

If telemetry is available, the constraint text still states
performance intent stays subordinate to thermal safety regardless -
S6.5 has no mechanism to override kernel/hardware thermal protection,
and does not claim to plan around it more cleverly than the kernel
already does.

## Battery efficiency (Section 62)

If a battery is present (S2's `power_policy.batteries`, reused),
`build_constraints()` notes the possible conflict:

> "A battery is present - a requested high-performance focus may
> conflict with battery-efficiency policy; S6.5 reports this conflict,
> it does not force maximum performance."

No policy ever forces a performance governor or overrides
battery-efficiency policy to satisfy a requested focus - the conflict
is surfaced, not resolved by brute force.

## Power profile relationship (Section 63)

S6.5 does not create a second, independent CPU power-profile engine -
S2's `power-profiles-daemon` detection and policy remain the only power
mechanism in this codebase. A focus policy may conceptually *prefer* a
power policy in a future runtime, but S6.5 itself never calls
`powerprofilesctl set` or `cpupower frequency-set` - confirmed by
regression (`tests/test_focus.py::TestNoMutationRegressions`) and
`serein focus doctor`'s `focus_plan_no_mutation` check, which scans
every policy's text for exactly these markers.

## System reserve (Section 64-65)

Every `FocusPolicy.memory_intent.system_reserve` is non-empty and
explicitly states no focus domain ever claims 100% of detected RAM/CPU
- "interactive system responsiveness is part of the system reserve" at
every target, including the primary-focus target itself. Checked
directly by `serein focus doctor`'s `focus_system_reserve_present`
check across all five targets.
