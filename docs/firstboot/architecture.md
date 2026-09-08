# First-Boot Provisioning Architecture (S7.2)

## Mission

> Convert a freshly installed Serein base into a coherent, initialized
> Serein workstation exactly once, safely and recoverably.

**S7.2 provisioning is installed-system initialization, not
installation.** S7.1 owns ISO -> installer -> target disk -> installed
bootable Serein base; S7.2 owns everything after that installed system
boots for the first time. **Successful completion must be idempotent
across all subsequent boots** - the central invariant this document
returns to repeatedly below.

The central safety invariant, enforced as code (not merely documented):

```text
NO VALID PENDING HANDOFF  =  NO PROVISIONING MUTATION
```

## Pipeline

```
Installed Serein base (S7.1 output)
      |
detect first-boot pending state      <- serein.firstboot.eligibility
      |
validate installation handoff        <- serein.firstboot.installstate
      |
block on live media / already done   <- serein.firstboot.livemedia
      |
acquire single-owner lock            <- serein.firstboot.lock
      |
transactional step sequence          <- serein.firstboot.steps + .engine
      |
mark provisioning complete           <- step 11 (install-state.json flip)
      |
normal subsequent boot (no-op)
```

This is the same Discover -> Resolve -> Plan -> Validate -> Apply ->
Verify -> Record lifecycle `docs/architecture/installer-contract.md`
mandates for every mutating operation in this repository:

| Contract stage | S7.2 module |
|---|---|
| Discover | `serein.firstboot.installstate` + `.livemedia` (handoff + environment) |
| Resolve | `serein.firstboot.eligibility` (the one ELIGIBLE/BLOCKED/NOT_REQUIRED verdict) |
| Plan | `serein.firstboot.plan` (`serein firstboot plan` - side-effect free) |
| Validate | step `01-validate-installation` (re-validates under the lock - TOCTOU) |
| Apply | `serein.firstboot.engine.run_firstboot` (only via `python -m serein.firstboot run --allow-run`) |
| Verify | step `10-final-validation` |
| Record | step `11-mark-complete` + `serein.firstboot.evidence` (`firstboot-evidence.json`) |

## S7.1 -> S7.2 handoff contract

S7.1 writes `/etc/serein/install-state.json`
(`serein.installer.payload.build_install_state_marker`,
`schemas/installer-install-state.schema.json`):

```json
{
  "schema_version": 1,
  "phase": "s7.1",
  "installation_complete": true,
  "firstboot_provisioning": "pending",
  "source_media_version": "26.04.1",
  "source_commit": "<40-hex-char commit sha>"
}
```

`serein.firstboot.installstate.read_install_state` reads and
structurally validates this file (reusing
`serein.installer.payload.InstallStateMarker` and
`serein.installer.models.INSTALL_STATE_SCHEMA_VERSION`/`INSTALLER_PHASE`
rather than redefining the schema). `serein.firstboot.eligibility.evaluate_eligibility`
is the single canonical gate every entrypoint calls:

| Handoff state | Verdict |
|---|---|
| missing, malformed, wrong schema/phase/types | `BLOCKED` |
| `installation_complete=false` | `BLOCKED` |
| `firstboot_provisioning` not one of `pending`/`complete` | `BLOCKED` |
| live-media evidence observed (Section 10) | `BLOCKED` |
| `firstboot_provisioning="complete"` | `NOT_REQUIRED` (no-op, not a failure) |
| valid + `installation_complete=true` + `firstboot_provisioning="pending"` | `ELIGIBLE` |

`evaluate_eligibility` never mutates anything - `status`, `doctor`, and
`plan` all call it directly; the mutating engine calls it once before
taking the lock, and step `01-validate-installation` re-derives the
same facts again *after* the lock is held, closing the TOCTOU window
between the pre-lock check and the first real mutation.

## Two state files, two responsibilities

- `/etc/serein/install-state.json` - S7.1's installation-provenance
  record. S7.2 only ever mutates its `firstboot_provisioning` field,
  exactly once, in the final `11-mark-complete` step - every other
  field (`source_commit`, `source_media_version`, `phase`,
  `schema_version`) is preserved verbatim so S7.1's own audit evidence
  is never destroyed (Section 30).
- `/var/lib/serein/firstboot/state.json` - S7.2's own transactional
  state machine (`serein.firstboot.models.FirstbootState`). This is the
  authoritative source for "has firstboot already run" from S7.2's own
  perspective - independent of whether the install-state.json flip has
  landed yet, so a crash between the last step passing and that flip
  can never cause re-provisioning.

## The state machine

Four states (Section 7): `pending -> running -> complete`, with
`failed` reachable from `running` and retryable back into `running`.
`repair_required` is deliberately not modeled - S7.2 has no repair
mechanism (that is S7.3's job), so a state it could never transition out
of would misstate reality.

```
        (ELIGIBLE, first run)
pending ----------------------> running
                                   |  |
                     each step   pass|  |fail
                     checkpointed  |  |
                                   v  v
                              complete  failed
                                          |
                                   (retry, ELIGIBLE)
                                          |
                                          v
                                       running
```

## Step lifecycle (Section 8-9)

Eleven named, ordered steps (`serein.firstboot.steps.DEFAULT_STEPS`):

```text
01-validate-installation      re-validate handoff under the lock (TOCTOU)
02-initialize-directories     /etc/serein, /var/lib/serein(/firstboot), /var/log/serein (0755)
03-apply-core-config          hardware snapshot (S2) + default Focus baseline label ("balanced")
04-desktop-baseline           register S1 desktop status (registration/no-op - no unattended apply exists)
05-development-registration   register Forge (S3) toolchain status
06-ai-registration             register Aether (S4) backend/runtime readiness
07-cyber-registration          register Ward (S5) capability state
08-privacy-registration        register Veil (S6) configuration state
09-system-services              document services policy (only serein-firstboot.service itself)
10-final-validation             confirm every prior step's persisted status is "passed"
11-mark-complete                 flip install-state.json firstboot_provisioning -> "complete"
```

Each step is `id, status, started_at, completed_at, failure_reason`
(`serein.firstboot.models.StepRecord`) - deliberately more than a single
boolean, so a partial run leaves real step-level evidence behind. State
is checkpointed atomically (`serein.firstboot.atomic.atomic_write_json`)
after **every** step transition, not only at the end.

Steps 05-08 call the real, existing S1-S6.5 read-only `status`
detectors (`build_development_status`, `build_ai_status`,
`build_cyber_status`, `build_veil_status`) - never reimplementing
detection - and persist a compact registration file under
`/var/lib/serein/firstboot/`. This is **detect -> verify -> register**,
never "download/reinstall everything."

## Idempotency and retry semantics (Section 6, 29)

- An already-`"passed"` step is never re-run (`engine._run_locked`
  skips it) - this is what makes a successful run idempotent across
  every subsequent boot: once `state.state == "complete"`,
  `run_firstboot` returns `NOT_REQUIRED` immediately, before taking the
  lock's mutation path or touching any file.
- A step that fails stops the run immediately (remaining steps stay
  `"pending"`) - **first failure wins** (Section 9), reimplementing
  `distribution/scripts/record-failure.sh`'s "first stage failure wins,
  never overwritten" discipline for this in-process state machine
  (`engine._record_first_failure`): a later, unrelated failure never
  overwrites the first real blocker's evidence.
- On retry, the previously-failed step is re-attempted; if it now
  passes, its stale failure evidence is cleared (the recorded blocker
  no longer describes reality) and the remaining steps continue to
  completion in the same invocation.
- `tests/test_firstboot.py::TestEngine::test_crash_retry_does_not_duplicate_passed_steps_and_completes`
  is the real proof: step1 PASS, step2 PASS, step3 FAIL, "reboot"
  (a fresh `run_firstboot` call against the same persisted state);
  retry shows step1/step2 were not duplicated (same `started_at`), step3
  is retried and passes, and steps 4-11 continue to `complete`.

## Systemd integration

`distribution/systemd/serein-firstboot.service` - `Type=oneshot`,
`RemainAfterExit=yes`, ordered after `local-fs.target`/`sysinit.target`
and before `multi-user.target`/`graphical.target`. `ConditionPathExists=`
is only a coarse pre-filter (the handoff file existing at all) - real
eligibility/state validation always happens in Python
(`run_firstboot`), never trusted from file existence alone (Section 11).
`ExecStart` invokes the explicit, tripwire-gated
`python -m serein.firstboot run --allow-run` entrypoint - never the
interactive `serein` CLI. On a boot where provisioning is already
complete, the engine itself observes `state.state == "complete"` and
returns `NOT_REQUIRED` almost immediately having mutated nothing; the
unit does not need to mask/disable itself for this to hold.

## Command surface (Section 12)

The interactive `serein` CLI only ever exposes **read-only** firstboot
commands, mirroring `serein.installer`'s own separation:

```text
serein firstboot status [--json]     eligibility/state/step summary
serein firstboot doctor [--json]     PASS/WARN/FAIL/SKIP diagnostics
serein firstboot plan [--json]       side-effect-free preview of what a real run would do
```

There is deliberately no `serein firstboot run` command. Actual
mutation happens only via `python -m serein.firstboot run --allow-run`
(`src/serein/firstboot/__main__.py`) - the explicit, tripwire-gated
heavy-tooling entrypoint the systemd unit invokes, never something a
human runs casually from the interactive CLI.

## Concurrency and atomicity (Section 26-28)

- `serein.firstboot.lock.FirstbootLock` - PID file + `fcntl.flock`
  (non-blocking exclusive) on POSIX; the kernel releases the lock
  automatically on process exit/crash, so a crashed run can never leave
  a permanently stuck lock. Degrades to an exclusive-create fallback on
  a platform without `fcntl` (this repository's own Windows dev/CI host)
  - documented as **not** crash-safe, and never the production path.
- Every state/evidence/registration write goes through
  `serein.firstboot.atomic.atomic_write_json` - temp file in the same
  directory, `fsync` (best-effort), `os.replace` - never a partially
  written real file, even on power loss.
- Every write target is resolved via
  `serein.distribution.pathsafety.resolve_within` (the repository's
  established path-confinement helper) rather than raw path joining.

## Security boundaries preserved

- `GLOBAL_TOR_ENABLEMENT=false`, no Whonix auto-start (ADR-0021/0024) -
  step `08-privacy-registration` only ever calls the read-only
  `build_veil_status`.
- `AUTO_CYBER_EXECUTION=false` - step `07-cyber-registration` only ever
  calls the read-only `build_cyber_status` (itself restricted to
  `--version`/`--help`-style probes).
- `AI_MODEL_DOWNLOAD_COUNT=0` - step `06-ai-registration` never
  downloads a model or starts a permanent inference daemon.
- `FOCUS_APPLY=false` (ADR-0026) - step `03-apply-core-config` only
  ever writes a default Focus baseline **label** (`"balanced"`,
  `runtime_enforcement: false`, `applied: false`); no cgroup/scheduler
  mutation.
- No SSH/API/Tor key generation beyond normal subsystem behavior
  (Section 24) - S7.2 generates no secrets at all.
- No hardcoded username/home path (Section 25) - every subsystem status
  call passes `home=None`, letting the underlying S3/S6 detector degrade
  honestly rather than guessing a human user's home directory.

## Module map

```
src/serein/firstboot/
  models.py        dataclasses only - FirstbootState, StepRecord, EligibilityResult,
                     LiveMediaEvidence, FirstbootEvidence, etc. Path constants.
  installstate.py  read_install_state() - reuses serein.installer.payload.InstallStateMarker
  livemedia.py     detect_live_media() - multiple independent heuristics
  eligibility.py   evaluate_eligibility() - the one canonical read-only gate
  atomic.py        atomic_write_json/text - temp file + fsync + os.replace
  lock.py          FirstbootLock (fcntl-based, degrades on non-POSIX) + is_lock_held()
  statefile.py     FirstbootStateStore - load/save/reconcile FirstbootState
  steps.py         FirstbootContext, StepDefinition, StepOutcome, the 11 real step
                    functions, DEFAULT_STEPS
  engine.py        run_firstboot() - the only mutating entrypoint; first-failure-wins
  evidence.py      FirstbootEvidence assembly/write/load
  status.py        serein firstboot status
  doctor.py        serein firstboot doctor
  plan.py          serein firstboot plan
  __main__.py      python -m serein.firstboot - the explicit, --allow-run-gated
                    mutating entrypoint (mirrors serein.installer.__main__)
```

## Scope boundary

S7.2 owns: first-boot eligibility detection, handoff validation,
transactional/idempotent provisioning, Serein core directory/state
initialization, hardware-aware awareness snapshot, default Focus
baseline label, Forge/Aether/Ward/Veil registration, services policy
documentation, systemd first-boot integration, provisioning evidence.

S7.2 does **not** own: S7.1 installation itself, S7.3 recovery/rollback/
repair-shell/snapshot-restore, S8 performance benchmarking/Focus runtime
Apply/resource enforcement, per-user personalization bootstrap (a
future, separate contract - Section 25), Tor/Whonix activation, cyber
active scanning, AI model downloads, desktop UI redesign. See
`docs/firstboot/known-limitations.md`.

## Why a separate state file, not a single flag

Per `docs/roadmap.md`'s discipline of never collapsing distinct facts
into one fragile signal (mirrored from S6.5's `mechanism_available`/
`instance_present`/`instance_running`/`managed_by_serein` split -
`docs/adr/`), S7.2 deliberately keeps **installation provenance**
(S7.1's `install-state.json`) and **provisioning transaction state**
(S7.2's own `state.json`) as two files with two owners. Collapsing them
into one would force either S7.1 to carry S7.2's step-level detail it
has no way to produce, or S7.2 to treat S7.1's audit record as its own
scratch space - both wrong.
