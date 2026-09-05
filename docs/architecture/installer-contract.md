# Installer Contract (Design Only — S0 Implements No Mutation)

S0 must not modify the host. This document defines how future mutating
operations (package installation, service enablement, configuration file
writes, and eventually profile activation) are required to behave once
they are implemented in a later phase. Nothing described here executes
yet — there is no installer code in this repository.

## Lifecycle every mutating operation must implement

```
Discover  →  Resolve  →  Plan  →  Validate  →  Apply  →  Verify  →  Record
```

1. **Discover** — gather current host state (hardware, installed
   packages, existing configuration). Read-only; this is what `hardware
   probe` and `doctor` already do today.
2. **Resolve** — combine the requested profile(s) with discovered state to
   determine what actually needs to change (diff against current state,
   not a blind re-apply).
3. **Plan** — produce an explicit, inspectable list of actions (package
   installs/removals, service enable/disable, files to write, with
   before/after where applicable). The plan must be presentable to the
   user before anything happens.
4. **Validate** — check the plan against constraints (profile conflicts,
   hardware conditions, disk space, permission requirements) and refuse to
   proceed if validation fails, with a clear reason.
5. **Apply** — execute the plan. Must support a `--dry-run` mode that
   performs Discover/Resolve/Plan/Validate and prints the plan without
   executing it.
6. **Verify** — after applying, re-run the relevant checks to confirm the
   intended end state was actually reached (not just "the commands
   exited 0").
7. **Record** — persist what was done (which plan, when, against which
   prior state) so a future rollback has something to act on.

## Hard requirements for any future implementation

- **No silent destructive action.** Every mutating action must appear in
  the Plan step and be visible before Apply.
- **`--dry-run` is mandatory**, not optional, on every mutating command.
- **Rollback where practical.** A profile manifest's `rollback` field
  (`schemas/profile.schema.json`) must describe whether rollback is
  supported and how; `supported: false` must be an honest statement, not a
  default nobody revisits.
- **No `sudo` invoked by Serein on the user's behalf without an explicit,
  visible Apply step the user approved.** Serein does not silently
  elevate.
- **No curl-pipe-shell installers, no arbitrary third-party APT
  repositories** added without going through Plan/Validate the same as
  any other action.

## Why none of this exists yet

Implementing Apply before Discover/Resolve/Plan/Validate/Verify/Record are
solid would mean shipping a mutation path with no safety net. S0's job is
to prove the read-only half (hardware, doctor, profile *model*) is correct
and tested; S2 onward builds the mutating half on top of it. See
`docs/roadmap.md`.
