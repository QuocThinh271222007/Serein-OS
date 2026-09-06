# Development Subsystem Architecture (S3)

## Governing question

> What developer tools are installed, what stacks are supported, what
> conflicts already exist, what would Serein install/configure, where
> would each tool come from, and what requires root — without actually
> mutating the host?

## Three layers, mirroring S2's hardware architecture exactly

```
serein dev status         "what developer tooling exists"
serein dev capabilities   "what can Serein safely provision"
serein dev plan [comp]    "what would Serein do"
```

This is a deliberate repeat of ADR-0006's probe/capabilities/plan model
— proven in S2, reused here rather than inventing a second pattern.

## Module map

```
src/serein/development/
├── models.py         dataclasses only (ToolStatus, DevelopmentCapability,
│                     DevPlanAction, DevelopmentPlan, ...)
├── runner.py         injectable CommandRunner (real subprocess in
│                     production, fakes in tests) - see "Command safety"
├── _util.py          safe home-directory resolution for marker checks
├── toolchains.py     shared `probe_tool()` - one `<bin> --version` →
│                     ToolStatus pattern, used by every language module
├── git.py, python.py, node.py, rust.py, go.py, cpp.py, editor.py,
│   containers.py     one detector module per stack
├── packages.py       declarative tool/source manifest (data only)
├── resources.py      inert repo-root config templates (development/)
├── capabilities.py   "what can Serein provision"
├── planner.py        "what would Serein do" (the canonical plan;
│                     component filters subset it, never re-derive it)
├── status.py         human-readable aggregation for `serein dev status`
└── doctor.py         development-layer diagnostics
```

## Command safety (the core constraint this whole subsystem observes)

Every detector calls exactly one thing: `<binary> --version` (or an
equivalent read-only flag), through `runner.py`'s `CommandRunner`
abstraction — bounded by a timeout, `shell=False` always, never given an
install/update/login/container-creation command. A missing binary, a
timeout, or unparsable output all degrade to "not installed" — never an
exception, never `serein dev status` crashing. See
docs/development/known-limitations.md for exactly what this Windows/CI
development environment could and could not exercise.

## Why this augments S2's `dev` profile rather than creating a second one

S2 already introduced `dev` as a *hardware* resource-policy profile.
S3 does not create a `development` or `dev-workstation` profile
alongside it — it extends the same `profiles/dev/dev.profile.json`
manifest to also carry the software layer (packages, configuration
units, verification checks), consistent with Section 7's explicit
instruction. "Implemented" for `dev` now means: hardware policy (S2)
*and* development-tool detection/planning (S3) are both real — not that
either has actually installed anything on any host (see
docs/development/installation-plan.md).

## No Apply mechanism in S3

Identical constraint to S2: every detector is read-only, `planner.py`
never writes a package, runs an installer script, or touches a user
config file. A `DevPlanAction`'s `status` field
(`APPLY`/`NOOP`/`SKIP`/`BLOCKED`) describes what a *future* Apply step
would do, matching the S0 installer lifecycle's Discover → Resolve →
**Plan** → Validate → Apply → Verify → Record.

## The "installed vs. supported vs. managed" distinction

Same three-way split S1/S2 established:

- **Status** answers "does this tool already exist" (a `ToolStatus`).
- **Capabilities** answers "can Serein safely provision this stack here"
  — almost always `true` for user-level language tooling (it works
  identically under WSL and inside a container), with the one real
  exception being a container engine/Distrobox inside an already-nested
  container context.
- **Plan** answers "given current state, what would Serein propose" —
  evidence-based, gated on the exact same capability computation
  (`containers.container_capability_available()`) the capabilities
  report uses, so a plan action can never say `APPLY` where the
  capability model says unavailable (the invariant S2RM's corrective
  established for ZRAM, applied here from the start).

## Conflict handling

Coexisting tool managers (two Node managers, two container engines) are
never silently "fixed" — the planner reports `BLOCKED`/`NOOP` with an
explanation, and `serein dev doctor` reports `WARN`, never `FAIL`.
Existing user tooling is detected and respected, never removed.
