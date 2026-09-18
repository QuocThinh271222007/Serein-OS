# Known Limitations (S7.2)

## Layer A only - real runtime validation status

**S7.2 has never run against a real installed target.** Every test in
`tests/test_firstboot.py` runs against an injectable fixture root
(`tmp_path`) and a fake command runner - never a real installed Serein
system, never real systemd, never a real S7.1-produced qcow2. This
mirrors this repository's own established discipline (see
`docs/installer/known-limitations.md`, `docs/distribution/known-limitations.md`):
report `NOT_AVAILABLE`/`NOT_OBSERVED` honestly rather than fabricate a
pass.

Confirmed `NOT_AVAILABLE` in this development/CI environment (Windows):

- `systemd-analyze` - not installed; `distribution/systemd/serein-firstboot.service`
  has only ever been reviewed by hand and against the unit-file grammar
  documented in `man systemd.unit`/`man systemd.service` - never run
  through real `systemd-analyze verify`.
- Real `systemctl` - `serein.firstboot.doctor`'s systemd-unit check and
  `serein.firstboot.steps.step_system_services`'s `systemctl --version`
  probe both degrade to `SKIP`/`False` here, exactly as they are
  designed to on any non-systemd host.
- A real S7.1-installed target (qcow2 or otherwise) - does not exist in
  this workstream. S7.2 is intentionally being developed as a stacked,
  parallel branch while S7.1 is still under active corrective work (see
  the task brief's Section 2-3) - real integration with an actual
  installed image is explicitly future work (Section 42, below).

`S7_2_RUNTIME_LAYER_B=DEFERRED_UNTIL_S7_1_CLOSED` (Section 41 of the
task brief) - this is intentional, not an oversight: triggering a real
S7.2 VM-validation workflow now would compete with S7.1's own active
Installer Layer-B corrective runs for CI resources. No new
`pull_request`/`push`-triggered GitHub Actions workflow was added by
this branch for that reason.

## Future real Layer-B acceptance criteria (documented, not implemented)

The eventual real-Layer-B closure proof (topology: S7.1 installed-target
qcow2 -> boot under OVMF -> the real systemd `serein-firstboot.service`
runs -> wait for strong completion evidence -> shutdown/reboot -> boot a
second time -> prove firstboot did **not** rerun) will need to report,
honestly, from a real run:

```text
REAL_FIRST_BOOT
INSTALL_STATE_VALID
FIRSTBOOT_SERVICE_STARTED
FIRSTBOOT_PROVISIONING
FIRSTBOOT_FINAL_STATE=complete
SEREIN_CORE
DESKTOP_BASELINE
FORGE_STATE
AETHER_STATE
WARD_STATE
VEIL_STATE
GLOBAL_TOR_ENABLEMENT=false
AUTO_CYBER_EXECUTION=false
FOCUS_APPLY=false
SECOND_BOOT=PASS
FIRSTBOOT_SECOND_EXECUTION_COUNT=0
```

and, for the offline goal specifically, a future run with networking
disabled in the guest:

```text
REAL_OFFLINE_FIRSTBOOT=PASS
```

None of these fields exist anywhere in this codebase as fabricated
constants - they are documented here purely as the target shape a
future real VM run's evidence assembly should fill in, the same way
`docs/installer/known-limitations.md` pre-documents `REAL_*` fields
before any real run has produced them.

## Judgment calls made in this implementation

- **`serein firstboot run` is not a main-CLI subcommand at all** - the
  task brief allowed either an opt-in-flag-gated main-CLI command or a
  fully separate entrypoint; this implementation chose the latter
  (mirroring `serein.installer.__main__`'s exact separation) as the
  stricter, more consistent-with-existing-precedent option. Real
  mutation lives exclusively behind `python -m serein.firstboot run
  --allow-run`.
- **Desktop baseline (step `04`) verifies + records; it does not stage
  files itself** (Phase-7-completion Section 6/8/10) - the six
  `owner="system"` resources in `desktop.config.RESOURCES` are the
  idiomatic responsibility of a package/install-time mechanism (a
  future `serein-desktop` .deb, or curtin late-commands during
  install - see `SEREIN-DESKTOP-STAGING-PENDING` below), never a
  first-boot runtime copy. This step verifies every one of those
  target paths is actually present, then writes the
  `/etc/serein/desktop/config-version` marker and re-reads it back via
  the SAME `build_desktop_status()` detector desktop.plan/desktop.doctor
  already use - it fails closed (never falsely "applied") if staging
  has not happened yet. The two `owner="first-login-user"` resources
  (the Look-and-Feel package) are still deliberately left untouched -
  there is no user session inside a oneshot boot unit, and user config
  must never be overwritten after first boot.
- **Hardware apply (part of step `03`) is real but narrow** (Section
  25) - `serein.hardware.executor.apply_hardware_plan` consumes
  `build_hardware_plan("balanced", root)` unchanged and actually
  performs the two actions Section 25 names as examples:
  `set_power_profile` (via `powerprofilesctl set`/`get`) and
  `configure_zram` (writes this repo's own pinned
  `hardware/defaults/zram-generator.conf` to
  `/etc/systemd/zram-generator.conf.d/90-serein.conf`, never the base
  file, verified via `detect_memory_policy`). `cpu.epp`
  (`set_epp`, a per-core sysfs write) and the per-device IO-scheduler
  action are real `HardwarePlan` actions this executor does not yet
  implement - a real plan proposing either comes back
  `not_enforceable`, never silently dropped or falsely applied - see
  `SEREIN-HARDWARE-EXECUTOR-CPU-IO-PENDING` below. A single hardware
  action failing (e.g. no power-profiles-daemon on this host) never
  fails the step or the overall run - hardware tuning is optional
  polish, never release-blocking.
- **The systemd unit is not yet wired into `serein.installer.payload`'s
  build/packaging path** - `distribution/systemd/serein-firstboot.service`
  exists as a standalone artifact under `distribution/systemd/`.
  Copying it into a built ISO/target's payload is owned by whichever
  future change updates S7.1's payload assembly - deliberately not done
  here, since `src/serein/installer/` is explicitly off-limits to this
  parallel S7.2 workstream while S7.1R2 corrective work is in progress
  elsewhere.
- **Locking degrades on non-POSIX platforms** - `serein.firstboot.lock.FirstbootLock`
  uses real `fcntl.flock` (crash-safe: the kernel releases it
  automatically on process exit) on POSIX, and an exclusive-create
  fallback elsewhere. The fallback is *not* crash-safe (a stale lock
  file from a process that crashed without calling `release()` would
  need manual cleanup) - documented in `lock.py`'s module docstring.
  This only matters for this repository's own Windows dev/CI host;
  Serein's real target (Ubuntu/systemd) always uses the real `fcntl`
  path.
- **`[tool.mypy]` now pins `platform = "linux"`** - added so
  platform-conditional stdlib usage (the `fcntl` import above) type-checks
  against Serein's real deployment/CI target (`.github/workflows/*.yml`
  all run `ubuntu-latest`) rather than whatever OS a contributor's dev
  machine happens to run. This is a small, narrowly-scoped, and honest
  correction to the existing mypy config - not an S7.2-specific hack.
- **`network_available` is always `None` in evidence, never probed** -
  Section 23 requires core provisioning to succeed offline; rather than
  add a new network-reachability probe whose only purpose would be to
  populate an informational field, this implementation records `None`
  ("not probed") honestly instead of fabricating a boolean. Every S7.2
  test proves `COMPLETE` using a `FakeCommandRunner` that never touches
  a real network, which is itself the strongest available proof of
  `OFFLINE_FIRSTBOOT_CORE=SUPPORTED` at the Layer A level.
- **`home=None` for every S3/S6 status call** (Section 25) - first-boot
  provisioning runs as root via systemd with no logged-in human user, so
  guessing a home directory would be dishonest. The underlying detectors
  already degrade gracefully when `home` is `None`.
- **Per-user personalization bootstrap is explicitly not implemented**
  (Section 25) - S7.2 only ever performs system-level provisioning. A
  separate per-user first-login contract is left for a future change.

## What S7.2 deliberately does not implement (by design, not oversight)

- **S7.3 (recovery/rollback)** - `S7_3_RECOVERY_IMPLEMENTED=false`. On
  unrecoverable failure, `FirstbootState` persists `state=failed`,
  `first_failure_stage`, `first_failure_reason`, and every step's real
  status - enough for a future S7.3 to consume - but no auto-repair,
  recovery shell, snapshot restore, boot repair, or fallback slot exists
  here.
- **S8 (Focus Apply/resource enforcement)** -
  `S8_OPTIMIZATION_IMPLEMENTED=false`. Step `03-apply-core-config`
  writes a hardware *awareness* snapshot, applies the narrow S2
  hardware actions documented above, and writes a default Focus
  *label* only - never a cgroup write or scheduler change. See
  `docs/focus/` for the separate S6.5 Focus runtime workstream.

## Backlog (Phase-7-completion Section 27/58)

| ID | Area | Severity | Description | Reason deferred | Future validation |
|---|---|---|---|---|---|
| `SEREIN-DESKTOP-STAGING-PENDING` | firstboot / desktop | non-blocking | The six `owner="system"` desktop resource files are not yet staged onto any installed target by any mechanism (no `serein-desktop` package, no curtin late-commands step) - `step_desktop_baseline` will legitimately fail closed on a real system until this exists. | Belongs to the install/package pipeline, not first-boot itself; a real Debian package or curtin wiring is a separate, larger change (see Section 35's package-model discussion). | A real S7.1-installed target with the resources actually staged, then a real first-boot run observing `04-desktop-baseline` pass. |
| `SEREIN-HARDWARE-EXECUTOR-CPU-IO-PENDING` | firstboot / hardware | non-blocking | `serein.hardware.executor` does not yet implement `set_epp` (CPU energy-performance-preference sysfs write) or the per-device IO-scheduler action - a real plan proposing either reports `not_enforceable`. | Scoped out of this round to keep the first real hardware-executor pass small and fully tested; both are well-understood sysfs writes, not an open design question. | Extend `_IMPLEMENTED_ACTIONS` and add a real sysfs-write implementation, tested the same way (`tests/test_hardware_executor.py`) against a fixture root. |

## Pre-existing, unrelated test failure observed on this branch

`tests/test_distribution.py::TestInspector::test_fixture_extracted_tree_passes`
fails on this Windows development host both **before** and **after**
every S7.2 change in this branch (confirmed via `git stash` against the
unmodified S7.1 HEAD this branch was created from) - it is unrelated to
first-boot provisioning, lives in the distribution/ISO-inspection
subsystem, and is not touched by this workstream. Reported here for
honesty rather than silently ignored; see the S7.2 report's
`PRIOR_PHASE_REGRESSION` field.
