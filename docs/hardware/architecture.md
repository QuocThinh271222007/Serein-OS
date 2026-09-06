# Hardware Subsystem Architecture (S2)

## Governing question

> What hardware is this, what can I safely control, and what resource
> policy makes sense for the requested workload?

S2 answers this with three layers, each a real CLI surface, none of which
mutates the host:

```
serein hardware probe          "what hardware exists"   (S0, unchanged)
serein hardware capabilities   "what can Serein control" (S2, new)
serein hardware plan <profile> "what would Serein do"    (S2, new)
```

## Why this augments S0 rather than replacing it

`serein hardware probe` and `HardwareReport`/`SCHEMA_VERSION` in
`src/serein/hardware/models.py` are untouched — same fields, same schema,
same CLI output. Every S2 addition is new code that *reads* the same
injectable `root: Path` convention S0 established and either reuses
`probe_hardware()`'s output (e.g. the GPU list, the battery flag) or adds
a new, narrowly-scoped detector next to it. Nothing in S2 changes what
`hardware-report.schema.json` requires.

## Module map

```
src/serein/hardware/
├── (S0) _util.py, cpu.py, memory.py, gpu.py, storage.py, power.py,
│       environment.py, kernel.py, os_release.py, probe.py, models.py
│
├── (S2) cpu_policy.py      cpufreq driver/governor/EPP detection
├── (S2) memory_policy.py   swap + ZRAM detection
├── (S2) storage_policy.py  per-device I/O scheduler detection
├── (S2) power_policy.py    power-profiles-daemon presence + battery state
├── (S2) gpu_policy.py      hybrid-graphics + compute-driver detection
├── (S2) thermal.py         thermal_zone / hwmon presence
├── (S2) capabilities.py    "what can Serein control" — combines the above
├── (S2) planner.py         "what would Serein do" — the 5 hardware profiles
├── (S2) doctor.py          hardware-layer diagnostics
└── (S2) resources.py       inert repo-root policy artifacts (hardware/defaults/)
```

`models.py` gained new dataclasses (`CPUPolicyInfo`, `MemoryPolicyInfo`,
`StoragePolicyInfo`, `PowerPolicyInfo`, `GPUPolicyInfo`, `ThermalInfo`,
`Capability`/`CapabilitiesReport`, `PlanAction`/`HardwarePlan`) alongside
the S0 ones — one models module per subsystem, matching the convention
`desktop/models.py` and `profiles/models.py` already set.

## No Apply mechanism in S2

Every detector is read-only. `planner.py` never writes to sysfs, never
calls a package manager, never talks to D-Bus. A `PlanAction`'s `status`
field (`APPLY`/`NOOP`/`SKIP`/`BLOCKED`) describes what a *future* Apply
step would do — S2 stops at "propose and explain," matching the S0
installer lifecycle's Discover → Resolve → **Plan** → Validate → Apply →
Verify → Record (`docs/architecture/installer-contract.md`). A future S2R
(mirroring S1R's live-validation pattern) is the natural place to validate
a real, isolated Apply mechanism in a VM.

## The "installed vs. running vs. controllable" distinction

S2 adds a third axis to the "installed vs running vs Serein-managed"
model S1 established for the desktop layer:

- **Probe** answers "does this hardware/interface exist" (S0).
- **Capabilities** answers "can Serein safely act on it *here*" — the
  same interface existing is not sufficient if this is a WSL/container
  guest that doesn't own the mechanism (see `docs/hardware/
  planning-and-safety.md`).
- **Plan** answers "given a workload profile, what would Serein actually
  propose" — evidence-based, never guessed.

## Why every profile always generates a plan, never crashes

`planner.build_hardware_plan()` never raises for a supported profile id —
missing hardware degrades to `SKIP`/`BLOCKED` actions with an explicit
reason, not an exception. The one exception is the `battery` profile on a
battery-less host, which returns `profile_available=False` with a stated
reason and an empty action list — a profile being *inapplicable* is
different from the tool *failing*, and both are reported honestly rather
than one being disguised as the other (`docs/architecture/doctor-contract.md`
draws the same PASS/FAIL-vs-SKIP distinction).
