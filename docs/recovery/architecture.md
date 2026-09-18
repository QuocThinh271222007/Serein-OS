# Recovery / Repair / Fallback Architecture

Historical S7.3 scope, implemented as part of the unified Phase-7
completion program (Section 37-41).

## Scope

Recovery in this round covers **managed-file integrity** only - the
files Serein itself owns and can independently verify or regenerate.
It does not (yet) cover firstboot-transaction recovery or Focus-
transition recovery, because both of those already have their own
real recovery mechanics built directly into their own subsystems:

- **Firstboot recovery** is `serein.firstboot`'s own job: the
  persisted `FirstbootState` already records `first_failure_stage`/
  `first_failure_reason` and every step's real status, a crashed run
  resumes from exactly where it left off (idempotent retry, already
  tested), and it never re-runs a step already recorded as `passed`.
- **Focus recovery** is `serein.focus.runtime`'s own job: the
  transaction executor never updates the persisted active-focus state
  before every slice write verifies, so a crash mid-transition simply
  leaves the previous committed focus in place - there is no
  "requested but not yet verified" state that could be read back as
  real.

Neither of those needed a *separate* recovery module bolted on top -
building one would have duplicated logic that already exists and is
already tested (Section 2 - reuse before rewrite).

## Managed-file classification (Section 39)

Every managed file falls into one of two classes:

- **Regeneratable** (`/etc/os-release`, `/etc/issue`,
  `/etc/issue.net`): this system can recompute the exact expected
  content itself, via a pure function already shipped in the wheel
  (`serein.branding.os_identity`). `serein.recovery.checks` compares
  the file's real content against that function's output directly -
  never a separately maintained checksum database (Section 36 - no
  duplicate source of truth). `repair` can fix these.
- **Source-staged** (the six `owner="system"` desktop resources from
  `desktop.config.RESOURCES`): their expected content lives in the
  repository tree, which does not exist on an installed system (the
  same `SEREIN-DESKTOP-STAGING-PENDING` gap
  `serein.firstboot.steps.step_desktop_baseline` already documents).
  Only presence can be verified honestly - these always classify as
  `UNKNOWN` when present, never falsely `OK`. `repair` cannot fix
  these; Section 39's "do not blindly overwrite intentionally
  user-owned files" applies just as much to a file this system cannot
  independently prove the correct content of.

## CLI surface (Section 38)

```
serein recovery status   # read-only summary
serein recovery doctor   # read-only, PASS/WARN/FAIL (reuses the SAME
                          # serein.doctor.models.DoctorReport shape
                          # every other subsystem's doctor uses)
serein recovery plan     # read-only, side-effect-free preview

python -m serein.recovery repair --allow-repair   # the ONE mutating
                                                    # entrypoint
```

Mirrors `serein.firstboot`/`serein.installer`'s own established
separation: read-only surfaces live in the main interactive CLI;
mutation lives exclusively behind a distinct entrypoint gated by an
explicit flag (Section 38 - "Mutation must require explicit
acknowledgement").

## What repair actually does

`repair_managed_files` only ever touches the three regeneratable
files. For each: if already `OK`, it is left untouched (no
unnecessary write, no timestamp churn); otherwise it is regenerated
via `atomic_write_text` (fsync + rename - a crash mid-write can never
leave a truncated file) and immediately re-checked to confirm the
repair actually took effect before reporting success.

## Known limitation

Recovery has never run against a real installed/corrupted system -
every test in `tests/test_recovery.py` runs against an injectable
fixture root (`tmp_path`), matching this project's own established
Layer A discipline. Real runtime validation (deliberately corrupt a
real installed target's `/etc/os-release`, run `serein recovery
status`/`repair` for real, confirm it heals) is deferred to the
dedicated external-disk physical validation phase.
