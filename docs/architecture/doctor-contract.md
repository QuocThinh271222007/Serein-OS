# Doctor / Diagnostic Contract

## Result model

Every check produces exactly one of:

- **PASS** — the condition holds.
- **WARN** — the condition doesn't hold or couldn't be confirmed, but it
  does not prevent Serein's foundation from functioning (e.g. an
  unexpected but plausibly-supportable CPU architecture).
- **FAIL** — a foundation-level requirement is not met (e.g. Python too
  old, unsupported OS family).
- **SKIP** — the check does not apply in this context (e.g. checking
  `/proc` availability when not running on Linux at all).

## Scope: foundation only

S0's checks answer "can Serein reason about this host at all", not "is
every future capability available." Concretely, in scope:

- OS family (Linux) and CPU architecture (x86_64).
- Python runtime version.
- `/proc` and `/sys` availability.
- Contract schema files exist and parse as JSON.
- The hardware probe runs without raising.

Explicitly **out of scope for S0**, and must never be marked FAIL here:
CUDA/GPU driver presence, desktop environment presence, container runtime
presence, or any other capability that belongs to a later phase. A check
for those can be added when that phase implements the capability it would
gate.

## Exit code semantics

`serein doctor` exits:

- **0** if no check result is FAIL (WARN/SKIP do not affect the exit code).
- **1** if at least one check result is FAIL.

This is intentionally coarse: doctor is meant for "is the foundation
sound", answered as a single yes/no via exit code, with the finer detail
available in the printed/`--json` report. Exercised by
`tests/test_doctor.py`.

## Machine-readable output

`serein doctor --json` emits an object matching
`schemas/doctor-report.schema.json`: `schema_version`, a `summary` count
per status, and the full `checks` list. No timestamps are included —
output is deterministic for identical host state, which keeps golden-file
style assertions in tests stable.

## Adding a check

A new check is a function `(-root: Path) -> CheckResult` added to
`_ALL_CHECKS` in `src/serein/doctor/checks.py`. It must:

- Never raise (catch what it needs to internally, or rely on the
  hardware/probe layer's own safety net).
- Justify FAIL vs WARN by whether the condition blocks Serein's foundation
  or merely deviates from the primary target.
- Come with a fixture-backed test.
