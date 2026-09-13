# Known Limitations (S7.1)

## Real Layer-B validation status (S7.1R16)

**Sixteen real Installer Layer-B runs have occurred.** Run #16
(RUN_ID=34768219149, JOB_ID=103752927606,
HEAD=44e3ee72ce9503fbac9a102fb23c7c084c04e244 - the S7.1R15 dual-path
evidence commit) reproduced the SAME catastrophic snap/bootstrap
pathology as Runs #7/#11/#12/#15, while storage again progressed
cleanly through filesystem apply, partitioning, and extract:

```text
Run 16 (after S7.1R15):
  RUN_ID=34768219149, RUN_NUMBER=16
  HEAD=44e3ee72ce9503fbac9a102fb23c7c084c04e244
  RESULT=FAILURE - failure_stage=installer_timeout
  (qemu_timeout_seconds=6600).

  RUN16_RAW_ARTIFACT_DIRECTLY_READ=BLOCKED - this environment has no
  `gh` CLI and no local copy of ARTIFACT_ID=10322778412; the figures
  below are the task's own given, authoritative Run #16 summary, never
  an independent read.

  PROVEN (as given): storage again progressed cleanly -
  Filesystem apply ~4497.249s->~4522.504s PASS, partitioning
  ~4786.801s->~4835.988s PASS, extract ~4950.800s->~6513.177s PASS,
  curthooks starting ~6569.701s before the 6600s host timeout.
  RUN16_BLOCK_PROBE_PATHOLOGY=PROVEN_FALSE. This is now the SECOND
  consecutive run (after #15) with a clean storage path, further
  reinforcing that the R13/R14 block-probe pathology is not
  deterministic.

  PROVEN (as given): a genuine 3-attempt snapd.seeded lifecycle -
  attempt 1 ~446.911s->~610.211s FAIL, attempt 2
  ~1787.025s->~2476.805s FAIL, attempt 3 ~2784.058s->~4193.690s
  SUCCESS (seed_attempt_count=3, unstable_seed_window≈3746.78s
  ≈62m27s). Critically, the given Run #16 timeline places the FIRST
  observed abnormality at snapd.service's own startup (~519s estimated
  timeout, ~610s "timeout exceeded while waiting for response",
  ~624.759s/~714.560s/~837.443s/~909.052s snapd.service start-timeout/
  restart cycle) - HUNDREDS of seconds BEFORE the
  desktop-security-center hook failure (~1073.763s). This directly
  overturns this project's own prior working assumption:
  DESKTOP_SECURITY_CENTER_IS_INITIAL_TRIGGER=PROVEN_FALSE. The current
  earliest known abnormal area is snapd startup/initialization itself;
  SNAPD_STARTUP_ROOT_CAUSE=NOT_OBSERVED (why snapd fails to complete
  startup in time remains genuinely unknown from evidence available in
  this environment).

  PROVEN (as given): R15's dual-path telemetry DID run in the real QA
  session and DID execute real snap-state inspection (`snap changes`
  returned 5 real Changes, Change 1 = Error/"Initialize system state",
  Changes 2-5 = Done) - GUEST_EVIDENCE_TRANSPORT=PROVEN_PASS. But the
  exported frame only appeared at ~4269.64s (autoinstall extraction/
  load themselves only occurred at ~4259.922s/~4266.617s, i.e. AFTER
  the ~446s-4193s pathology had already resolved) -
  REALTIME_SNAP_PATHOLOGY_WATCHING=PROVEN_FALSE. Collection was
  retrospective, not real-time - the root motivation for this round.

  S7.1R16 fixes (still observability-only - no functional snap
  mitigation implemented):

  1. Objective A: the guest evidence watcher is no longer launched via
     Subiquity autoinstall early-commands at all -
     AUTOINSTALL_EARLY_COMMAND_DEPENDENCY_REMOVED=true. It is now
     embedded as a real, executable file at the QA-install ISO's own
     root (`serein.installer.isoprep` - the SAME "outer ISO
     filesystem, never the squashfs" placement `autoinstall.yaml`
     already uses) and started via a new, single-word
     `systemd.run=/cdrom/serein-qa-early-watcher.sh` kernel token on
     the QA boot entry only - the same proven, generalized
     kernel-token mechanism as every prior QA-only boot customization
     (R3's `autoinstall`, R5's journald-forwarding, R7's debug
     logging, R9's firmware-notifier mask). A new
     `SEREIN_EVIDENCE_WATCHER_STARTED` boot marker (with the guest's
     own monotonic timestamp) is the mechanism by which Run #17 proves
     or disproves whether this actually starts early enough - never
     assumed merely because the token exists. **Caveat honestly
     carried forward**: whether the real Ubuntu 26.04 live
     environment's systemd actually supports/honors `systemd.run=` at
     a point early enough to precede the first snapd failure is NOT
     validated in this development environment (no real QEMU/live-ISO
     boot here) - Run #17's own boot-marker timestamp is the real
     test, not assumed true.
  2. Objective B: dynamic, bounded failed-Change task-graph capture
     (`QA_EVIDENCE_MAX_FAILED_CHANGE_IDS=5`) - `snap changes`' own
     Status column is scanned for Error-like entries (never hardcoded
     to Change ID 1), and `snap tasks <id>` is captured for each,
     bounded.
  3. Objective C: narrow `systemctl show snapd.service` property
     capture (ActiveState/SubState/Result/NRestarts/ExecMainPID/
     ExecMainCode/ExecMainStatus/*TimestampMonotonic/TimeoutStartUSec)
     plus a bounded `journalctl -u snapd.service` window.
  4. Objective D: a best-effort "last snapd-tagged journal line before
     the first timeout-style message" reconstruction - never asserts
     this proves a deadlock, a plain bounded observation.
  5. Objective E: a narrow, read-only `ps` process snapshot of
     `snapd` (PID/state/elapsed/CPU time) - no ptrace, no memory dump,
     no debugger attach.
  6. Objectives F/G: explicit ordering timestamps
     (hold_start_ts/hold_finish_ts/portal_failure_ts/dsc_failure_ts/
     snapd_failure_ts) recorded in every frame, with
     `installer/scripts/extract-guest-evidence.sh` now computing
     honest ordering booleans (`unknown` whenever either side was
     never observed, never guessed) across every parsed frame -
     `snapd_failure_precedes_hold`,
     `snapd_failure_precedes_portal_failure`,
     `snapd_failure_precedes_desktop_security_center_failure`. Purely
     temporal observations, never promoted to a causal claim.
  7. Objective I: a real, proven case-sensitivity defect in the R14/
     R15 storage-probe semantic state machine - `line ~ pattern` in
     awk is case-SENSITIVE, but the real upstream finish-line format
     capitalizes SUCCESS ("finish: ...SUCCESS: restricted=False"),
     which this script only ever matched as lowercase "success"
     (relying on the OUTER grep's case-insensitivity, which never
     covered these four per-line checks). A real Run #16 unrestricted
     probe start followed by that finish line was silently MISCOUNTED
     as a SECOND start rather than closing the first attempt as a
     success. Fixed via `tolower()` on both the line and every pattern,
     rather than enumerating case variants - reproduced exactly
     against the real Run #16 timestamps (start ~4497.249s, finish
     ~4522.488660s) before and after the fix.
  8. Section 16 follow-through: Section 16's exists/nonempty split
     (R15) is unchanged and confirmed still correct this round.

  No functional snap-lifecycle mitigation implemented -
  SNAP_MITIGATION_IMPLEMENTED=false. The mitigation-eligibility
  checklist (Section 10 of this round's own corrective) is not met:
  this environment still has no raw serial log, no snapd Change/Task
  API access, and no local real-QEMU reproduction capability to
  establish WHY snapd's own startup exceeds its expected deadline
  before any corrective could be safely proposed.

  Explicitly NOT done this pass: QEMU timeout (6600s) and job timeout
  (270min) both UNCHANGED - Run #16 spent ~3746s in the snap pathology
  before meaningful storage progress, so it does not fairly test
  either budget; changing either would hide the pathology rather than
  address it. Storage selection, protected-disk visibility, target
  fixture layout, storage YAML grammar, and the R14 block-probe
  evidence path are all unchanged - confirmed via diff against the
  exact pre-head commit.
```

## Real Layer-B validation status (S7.1R15)

**Fifteen real Installer Layer-B runs have occurred.** Run #15
(RUN_ID=34749167021, HEAD=0966ac8a3162ba3dcb0de7486a814242f084ee14 -
the S7.1R14 guest-evidence-producer commit) did NOT reproduce the
Run #13/#14 block-probe pathology - storage progressed cleanly through
filesystem apply, partitioning, and extract - but DID reproduce the
recurring, nondeterministic snap/bootstrap pathology first seen in
Runs #7/#11/#12:

```text
Run 15 (after S7.1R14):
  RUN_ID=34749167021, RUN_NUMBER=15
  HEAD=0966ac8a3162ba3dcb0de7486a814242f084ee14
  RESULT=FAILURE - failure_stage=installer_timeout
  (qemu_timeout_seconds=6600).

  This environment has no raw Run #15 serial log, no live-guest
  access, and no local-real-QEMU reproduction capability -
  RUN15_RAW_ARTIFACT_DIRECTLY_READ=BLOCKED, the same limitation as
  every prior round. The figures below are the task's own given,
  authoritative Run #15 summary - RAW_SERIAL_LOG remains the
  authoritative source whenever it does become available; this
  section documents the given summary, never a direct read.

  PROVEN (as given): storage progressed cleanly this round -
  Filesystem/apply_autoinstall_config ~4128.357s->~4391.429s PASS,
  stage-partitioning ~4374.873s->~4415.353s PASS, stage-extract
  ~4502.447s->~5725.360s PASS, curthooks active near the timeout, old
  target sentinels replaced. RUN15_BLOCK_PROBE_FAILURE=PROVEN_FALSE.
  This directly demonstrates the Run #13/#14 storage-probe pathology
  is NOT deterministic - the same storage code can and does complete
  correctly.

  PROVEN (as given): a genuine 3-attempt snapd.seeded lifecycle -
  attempt 1 ~422.431s->~581.546s FAIL, attempt 2
  ~1715.404s->~2401.800s FAIL, attempt 3 ~2629.471s->~3871.714s
  SUCCESS (seed_attempt_count=3, unstable_seed_window≈3449.28s
  ≈57m29s) - with the same critical sequence as Runs #7/#11/#12: a
  desktop-security-center configure-hook failure (~821.731s), an
  associated sanity timeout (~821.747s), RemoveSnapServices beginning
  (~840.715s), `/snap/snapd/current` going missing (~1726.219s), and
  eventual stable recovery (~3871.714s).
  RUN15_CATASTROPHIC_SNAP_LIFECYCLE_RECURRED=PROVEN.

  Historical recurrence now spans Runs #7, #11, #12, #15 (pathological)
  against Runs #8, #9, #10, #13, #14 (normal) -
  RECURRING_NONDETERMINISTIC_PATHOLOGY=PROVEN, not a one-off outlier.
  The exact differentiating variable between the two groups remains
  genuinely unknown from evidence available in this environment -
  SNAP_ROOT_CAUSE_STATUS=NOT_OBSERVED (the same honest conclusion
  reached in R11/R12, for the same reason: no raw serial log, no
  snapd Change/Task API access, and no local real-QEMU reproduction
  capability to establish a specific, narrow, deterministic trigger).

  S7.1R15 fixes (observability-only, per this round's own explicit
  decision principle - the last corrective must diagnose BOTH
  pathology families, not optimize for whichever happened most
  recently):

  1. Objective B: the guest-side evidence watcher
     (`serein.installer.renderer._qa_evidence_watcher_script`) now
     also polls the guest's own systemd journal (a single bounded
     `journalctl -n 200` fetch per 10s iteration, never a fresh
     invocation per signal) for the five known snap-pathology signals
     above, exporting one bounded `SEREIN SNAP FAILURE FRAME` through
     the same QA-only, one-way virtio-serial port the R14 crash
     watcher already uses - at most once per signal per run
     (`QA_EVIDENCE_MAX_SNAP_FRAMES=5`,
     `QA_EVIDENCE_MAX_BYTES_PER_SNAP_FRAME=8192`). Genuinely
     unavailable diagnostic state (no user session/DBus for the
     portal check, no snapd.hold unit, etc.) reads as `NOT_OBSERVED`,
     never fabricated. `installer/scripts/extract-guest-evidence.sh`
     now parses both block kinds from the same raw evidence log,
     producing `qa-install-snap-failure-frame-N.txt` artifacts
     alongside the existing crash artifacts - Run #16 (or any future
     run) can now diagnose EITHER pathology family, BOTH, or NEITHER
     without requiring another observability-only round.
  2. Section 16: fixed a real field-name collision Run #15 exposed -
     `run-qa-install.sh`'s own `_write_result` and
     `extract-guest-evidence.sh` both called a field "present" while
     meaning two different things (`[ -s ... ]` nonempty-only vs.
     `[ -f ... ]` exists-only - a real QEMU chardev `file` backend
     creates the file the instant it opens it, so "exists" is
     trivially true almost immediately regardless of whether the
     guest watcher ever wrote anything). Split into
     `guest_evidence_log_exists`/`guest_evidence_log_nonempty` in
     both producers - never overloaded again.

  Per Section 10's explicit 10-point mitigation-eligibility checklist,
  a narrow functional snap-lifecycle mitigation was NOT implemented
  this round - the same blockers as R11/R12 apply
  (QA_ONLY_MITIGATION_ACCEPTABLE=false): no raw serial log, no snapd
  Change/Task API access, and no local real-QEMU reproduction
  capability to independently establish a specific, narrow,
  deterministic trigger before any mitigation could be safely
  proposed. SNAP_MITIGATION_IMPLEMENTED=false.
  DESKTOP_SECURITY_CENTER_MITIGATION=NOT_IMPLEMENTED (Section 12's own
  proof requirements are not met from evidence available in this
  environment). SNAPD_SEEDED_FAKED=false.

  Explicitly NOT done this pass: QEMU timeout (6600s) and job timeout
  (270min) both UNCHANGED - Run #15 spent ~3449s in the snap
  pathology before meaningful storage progress could even begin, so
  it does NOT fairly test whether 6600s is sufficient for a normal
  bootstrap path; changing either timeout now would hide the
  pathology rather than address it. Storage selection, protected-disk
  visibility, target fixture layout, storage YAML grammar, and the
  R14 block-probe evidence path are all unchanged - confirmed via
  diff against the exact pre-head commit.
```

## Real Layer-B validation status (S7.1R13)

**Thirteen real Installer Layer-B runs have occurred.** Run #13
(RUN_ID=34706519567, ARTIFACT_ID=10303419050) did NOT reproduce the
catastrophic snap lifecycle seen in Runs #7/#11/#12 -
RUN13_CATASTROPHIC_SNAP_LIFECYCLE_RECURRED=PROVEN_FALSE (snapd.seeded
completed a single, ~507s attempt: start ~449.643s, finish
~956.490s). The blocker moved to a NEW area entirely:

```text
Run 13 (after S7.1R12):
  RUN_ID=34706519567, RUN_NUMBER=13
  HEAD=a0dba2caa47b4234b29e3131bd609b469a9c2dcf
  RESULT=FAILURE - failure_stage=installer_timeout
  (qemu_timeout_seconds=6600, qemu_accelerator=tcg).

  Given evidence: Subiquity entered autoinstall (extract ~1180s, load
  ~1251s, apply ~1303s, Install/install ~1304s) then began real
  storage/filesystem probing - Filesystem/_probe/probe_once cycled
  between restricted=False failures/cancellations and restricted=True
  successes, then ANOTHER unrestricted probe occurred later. By
  >6200s, filesystem probes were still being attempted when the 6600s
  host timeout killed QEMU.
  SUBIQUITY_STORAGE_PROBE_FAILURE=PROVEN,
  FILESYSTEM_APPLY_AUTOINSTALL_COMPLETION=NOT_OBSERVED,
  CURTIN_PARTITIONING_STARTED=NOT_OBSERVED. An early curtin apt-config
  event must NEVER be read as proof partitioning started - real
  partitioning was not observed.

  Protected disk (/dev/vda, serial=SEREIN-PROTECTED-DISK) remained
  unchanged at container/logical/ESP-sentinel/data-sentinel level -
  PROTECTED_DISK_SAFETY=PROVEN_PASS. Target disk activity was
  observed (container/logical hash changed) but old target sentinels
  were STILL PRESENT afterward - OLD_TARGET_LAYOUT_REPLACED=PROVEN_FALSE,
  TARGET_REPARTITIONING=NOT_OBSERVED (metadata-level probing/mount
  activity, never confused with real partitioning proof).

  **Root-cause investigation (Objectives A-D)**: this environment has
  no raw Run #13 serial log, no live-guest access, and no
  local-real-QEMU reproduction capability - the exact trigger cannot
  be independently proven from Serein's own captured evidence this
  round. Real, cited upstream documentation (canonical/subiquity,
  bugs.launchpad.net/subiquity - LP #1868817, LP #2024011) was
  consulted and materially informs classification without itself
  being Serein-specific proof:
    - the real log format is "... probe_once: FAIL: cancelled" and
      "ERROR block-discover:NNN block probing failed restricted=False"
      (note: "failed" appears BEFORE "restricted=False" in this real,
      cited format - a genuine, order-dependent parser defect this
      corrective found and fixed while building the new forensics
      script - see below);
    - `probe_once` carries a documented internal ~15s timeout on its
      own full-probe task, and Subiquity's controller architecture is
      DESIGNED to fall back from an unrestricted (full) probe to a
      restricted probe on failure, then re-attempt unrestricted later
      - the exact unrestricted->restricted->unrestricted cycle Run #13
      observed matches this documented, intentional resilience
      pattern, not inherently a hang by itself;
    - Subiquity's own `match` autoinstall directive (serial/model/
      vendor/path/id_path/devpath/ssd/size/install-media) and
      probert's own public interface expose NO documented mechanism
      to exclude a specific, visible block device from being probed -
      probert probes every visible device by design; `match` only
      affects which ALREADY-PROBED disk gets SELECTED afterward.
      **SAFE_PROBE_MITIGATION_FOUND=false** follows directly.
  Best-supported classification: **C. SUBIQUITY_FILESYSTEM_CONTROLLER_RETRY_LOOP**
  (INFERRED, not PROVEN from Serein's own Run #13 evidence) - a
  documented real Subiquity resilience pattern, plausibly compounded
  by genuinely slow real subprocess I/O (blkid/parted/udevadm-class
  tools) under TCG software emulation across two virtio-blk disks,
  rather than a Serein-introduced defect.
  DESKTOP_SECURITY_CENTER_HOOK_FAILURE etc. are irrelevant this round
  (Objective H's own user-level firmware-notifier observation is
  tracked separately below, confirmed NOT the primary blocker).

  **Storage config audit (Objective C)**: direct code review of
  `render_autoinstall_storage_config`
  (`src/serein/installer/renderer.py`) re-confirms
  TARGET_SELECTION_CORRECT=PROVEN - the disk `match` stanza uses
  `serial` (SEREIN-TARGET-DISK) as its primary key, then `wwn`, then
  `path` as the final anchor - never `/dev/vdb` ordinal selection,
  never first/largest-disk, never implicit ordering. This selection
  logic runs entirely independently of, and AFTER, Subiquity's own
  pre-selection PROBE_VISIBILITY phase (which probes every visible
  device regardless of which one will later be selected) - the two
  concerns are structurally distinct, confirmed by direct reading,
  not conflated.

  **Target fixture audit (Objective E)**: `create-fixture-disks.sh`'s
  target disk is deliberately pre-populated with a GPT, a FAT32 ESP
  carrying an `EFI/Microsoft/Boot/sentinel.txt` path, and an ext4 data
  partition labeled `OLD_DEBIAN_DATA` - this is an EXPLICIT, documented
  part of the Section 32 test contract ("prove Serein intentionally
  REPLACES a pre-existing layout only after explicit targeting"), not
  stale/accidental metadata. This IS exactly the kind of content real
  `os-prober` scans for (EFI Windows Boot Manager signatures) as part
  of its normal, intended function - a real, but bounded and expected,
  contributor to probe activity, never a defect requiring correction.
  FIXTURE_CHANGE_REQUIRED=NOT_PROVEN; the fixture is unchanged this
  round.

  **Static review (Objective H)**: Run #13 confirmed the R9
  system-level firmware-notifier mask
  (`systemd.mask=snap.firmware-updater.firmware-notifier.service`)
  remains effective (the 599-restart storm did not recur) but does
  NOT prevent a separate USER-level systemd manager from also
  attempting the same unit (~10 observed restart attempts before
  StartLimit stopped it). SYSTEM_LEVEL_MASK=EFFECTIVE,
  USER_LEVEL_UNIT_STILL_ACTIVE=PROVEN,
  RUN9_599_RESTART_STORM_RECURRED=PROVEN_FALSE,
  RUN13_PRIMARY_BLOCKER_FIRMWARE_NOTIFIER=NOT_OBSERVED (this is not
  Run #13's blocker - no user-level mitigation implemented this
  round, per this corrective's own explicit narrow-scope requirement;
  left for a future round if it ever becomes the primary blocker).

  S7.1R13 fixes (forensics-only - no speculative functional
  mitigation implemented, per Outcome B of this corrective's own
  acceptance standard):

  1. New `installer/scripts/extract-storage-probe-forensics.sh` -
     bounded, host-side, read-only extraction of Subiquity/probert/
     os-prober storage-probe forensic evidence (unrestricted/
     restricted probe start/success/failure counts, Filesystem-scoped
     apply_autoinstall start/finish, curtin's real
     `start:`/`finish:` `stage-partitioning` event convention -
     NEVER an `apt-config` mention alone - os-prober invocation count,
     protected/target disk probe-visibility observations, crash-report
     MENTIONS in console text, and a bounded/truncation-honest
     failure summary). Wired into `run-qa-install.sh`'s workflow step
     and the uploaded Layer-B artifact manifest
     (`qa-install-storage-probe-forensics.env`), with a direct static
     test proving the wiring.
  2. A real, order-dependent regex defect was found and fixed WHILE
     building this script: a naive `restricted=False.*failed`-style
     combined regex cannot match the real, cited upstream format
     "block probing failed restricted=False" (where "failed" appears
     BEFORE "restricted=False") - fixed with an order-independent,
     chained AND-match helper (`_count_lines_matching_all`) used for
     every multi-token check in this script.
  3. A real device-path pattern defect was also found and fixed: a
     bare `\b` word-boundary directly after "vda"/"vdb" never matches
     the real, partition-suffixed paths Section 4's own evidence
     explicitly lists (`/dev/vda1`, `/dev/vda2`, `/dev/vdb1`,
     `/dev/vdb2`) - there is no word boundary between a letter and an
     immediately-following digit. Fixed to match the bare device path
     OR any partition-number suffix.
  4. A real performance defect (the same class as S7.1R12's own
     per-Change-ID optimization) was found and fixed before commit: an
     early per-line-subshell implementation of the order-independent
     matching helpers took ~55s against just 400 matching lines on
     this project's Windows/MSYS2 development environment; rewritten
     as single-awk-pass helpers, the same workload now completes in
     ~5s, and a 4000-line fixture also completes in ~5s (real
     production Layer-B runners have far cheaper fork/exec, but this
     project's own established discipline is to never rely on that
     margin).

  **Architectural note** (same constraint as S7.1R12's own snap-
  change-forensics script): this project's ONLY host<->guest channel
  is the QEMU `-serial file:...` console log - there is no shared
  folder, no 9p mount, no virtio-fs share, so a genuine live-guest
  crash-report FILE copy (Objective A's literal request) is not
  achievable without a materially larger architecture change than one
  corrective round justifies. This script therefore extracts crash-
  report MENTIONS from the console TEXT (journald-forwarded thanks to
  S7.1R5's fix), never a live file copy -
  `block_probe_crash_report_present`/`_count` are honest textual-
  mention observations, not proof a real crash-report file's full
  contents were captured.

  Explicitly NOT done this pass: QEMU timeout (6600s) UNCHANGED - Run
  #13 spent thousands of seconds in a storage-probe retry condition
  before any real partitioning could even begin, so a timeout
  increase would hide the unresolved probe loop rather than address
  it (`6600_SECONDS_SUFFICIENT_UNDER_NORMAL_BOOTSTRAP=NOT_OBSERVED` -
  never asserted false as a general conclusion, since no run has yet
  completed a normal bootstrap all the way through under this
  budget). No protected-disk visibility change, no target-selection
  semantics change, no fixture change, no speculative snap-lifecycle
  mitigation, no user-level firmware-notifier mitigation - all
  confirmed via diff against the exact pre-head commit.
```

## Real Layer-B validation status (S7.1R12)

**Twelve real Installer Layer-B runs have occurred.** Run #12
(RUN_ID=34547988878, ARTIFACT_ID unavailable to this environment)
reproduced the same catastrophic snap-lifecycle pathology as Runs #7
and #11 - CONSECUTIVE_PATHOLOGICAL_RUNS_11_12=PROVEN, i.e. this is no
longer explainable as a rare outlier:

```text
Run 12 (after S7.1R11):
  RUN_ID=34547988878, RUN_NUMBER=12
  HEAD=77e7c263a91b5db4b5424921fa2b76292243bfc9
  RESULT=FAILURE - failure_stage=installer_timeout
  (qemu_elapsed_seconds=6600, installer_userspace_reached=true).

  Given real evidence: a genuine 3-attempt snapd.seeded lifecycle
  (attempt 1 ~436.447s->~595.544s fail; attempt 2 ~1688.742s->
  ~2135.624s fail; attempt 3 ~2791.869s->~4031.859s SUCCESS), a
  desktop-security-center configure-hook sanity-timeout failure
  (~1033.269s, "Change 1" per the given evidence), a real mass
  RemoveSnapServices sequence (~1052.857s onward), a
  `/snap/snapd/current` missing window (~1701.211s, itself tied to a
  second Change-1 task failure: "Prepare snap \"snapd\" for security
  profile setup"), and eventual real stable recovery before
  Subiquity/curtin ever started - unstable_seed_window≈3595.41s
  (≈59m55s). Historical comparison (Run #8 ~450s, #9 ~399s,
  #10 ~468s, #11 ~3943s pathological, #12 ~3595s pathological)
  confirms RUN_7_ONLY_OUTLIER=PROVEN_FALSE and
  RUN_11_ONLY_OUTLIER=PROVEN_FALSE.

  S7.1R12 fixes (forensics/parser-corrective only - see the R12
  decision principle below for why no mitigation was attempted):

  1. Objective B: `_extract_seed_attempts` (added S7.1R11) had ONE
     remaining real defect - its dedup logic only compared each
     candidate line to the IMMEDIATELY PRECEDING accepted line
     (`last_ts`/`last_kind`), which only catches a duplicate
     serialized rendering of the same real event when the two
     renderings are strictly ADJACENT in the raw log. Real Run #12
     evidence proved a real, unrelated snapd.seeded-matching line can
     interleave between the two duplicate renderings, so the
     adjacent-only check missed it and wrongly reported
     `seed_attempt_count=4` instead of the real 3
     (R11_SEED_ATTEMPT_DEDUP=PROVEN_FALSE). Fixed with a GLOBAL
     (event_type, timestamp, normalized content) semantic-identity
     set, checked against EVERY previously-seen candidate rather than
     just the immediately preceding one - verified against a
     synthetic reproduction of Run #12's own given evidence
     (reproduces `unstable_seed_window_duration=3595.41` exactly).
  2. Objectives C-G: a new script,
     `installer/scripts/extract-snap-change-forensics.sh`, adds
     bounded, host-side, read-only extraction of snap Change/Task,
     snapd.hold, `/snap/snapd/current`, and desktop-portal forensic
     evidence - Change IDs are discovered DYNAMICALLY (never
     hardcoded to "1"), and every numeric/text field is explicitly
     bounded (max 20 distinct Change IDs, max 200 chars per captured
     summary, with `truncated=true` recorded whenever a bound is hit
     - Section 18, never silent truncation). Wired into
     `run-qa-install.sh`'s workflow step and the uploaded Layer-B
     artifact manifest (`qa-install-snap-change-forensics.env`), with
     a direct static test proving the wiring (producer step exists,
     runs unconditionally, and its exact output path is in the
     artifact manifest - Section 19's own "a wiring bug is
     unacceptable" requirement).

  **Architectural note** (read before assuming a "live sampler" is
  what Objectives D/E/F/G describe): this project's ONLY established,
  tested QA-install-medium mutation mechanism is boot-parameter
  patching of one GRUB menuentry - there is no squashfs-modification
  tooling anywhere in this repository or its CI dependencies (no
  unsquashfs/mksquashfs in the workflow's own tool-install list), so
  injecting a NEW live-session runtime sampler (a systemd
  service/timer that periodically runs `snap changes`/`snap tasks`/
  `systemctl show` INSIDE the guest and reports back) is not
  achievable without a materially larger architecture change than one
  corrective round justifies. `extract-snap-change-forensics.sh`
  therefore extracts real Change/Task/portal/snapd.hold/
  snapd-current EVIDENCE FROM THE SAME raw serial log
  `extract-bootstrap-milestones.sh` already parses - real Run #12's
  own given evidence (systemd/snapd Change/Task failure text,
  xdg-desktop-portal activity) already appears on that console thanks
  to S7.1R5's `systemd.journald.forward_to_console=1` fix, so no NEW
  guest-side instrumentation is required to surface it.
  `T0`-`T6`-style "checkpoints" (Objective D) are therefore raw-log
  timestamp ANCHORS (snapd_hold_start/finish, hook-failure timestamp,
  first RemoveSnapServices timestamp, snapd/current-missing
  timestamp, final stable seed), never a live systemctl/journalctl
  snapshot - `portal_live_state_snapshot_supported=false` is recorded
  explicitly in every run's output, honest about this gap rather than
  fabricating live-sampling capability that does not exist.

  **Static review (Section 20)**: a full-repository search confirms
  Serein's own code contains zero functional logic touching
  `snapd.hold`, `desktop-security-center`, or `ubuntu-desktop-bootstrap`
  - `src/serein/installer/renderer.py` (the autoinstall.yaml
  renderer) never references any snap package/configuration at all,
  and `src/serein/installer/isoprep.py`'s only real mutation in this
  space remains the R9 firmware-notifier `systemd.mask=` kernel
  token, which is order-independent with every other chained token
  (autoinstall/journald-forwarding/debug-logging) and touches an
  entirely unrelated unit. SEREIN_OWNED_TRIGGER=NOT_OBSERVED.

  QA_ONLY_MITIGATION_ACCEPTABLE=false this round, for the same reason
  as R11: this environment has no raw serial log, no snapd Change/
  Task API access, and no local real-QEMU reproduction capability to
  independently verify a specific, narrow, deterministic trigger for
  the pathological Change before any mitigation could be safely
  proposed. QA_ONLY_SNAP_MITIGATION_IMPLEMENTED=false.

  Explicitly NOT done this pass: QEMU timeout (6600s) and job timeout
  (270min) both UNCHANGED - Run #12 does not fairly test either
  budget, since ~3595s was consumed by the pathological snap
  lifecycle before meaningful installer progress; changing either
  timeout now would hide the pathology rather than address it.
  Storage semantics, target fixture size, autoinstall activation,
  firmware-notifier QA mask, and primary/secondary failure-recorder
  scripts all unchanged - confirmed via diff against the exact
  pre-head commit.
```

## Real Layer-B validation status (S7.1R11)

**Eleven real Installer Layer-B runs have occurred.** Run #11
(RUN_ID=34489050155, ARTIFACT_ID=10162450136) reproduced a
catastrophic snap-lifecycle pathology closely matching Run #7's real,
earlier evidence - CATASTROPHIC_SNAP_LIFECYCLE_RECURRENCE=PROVEN:

```text
Run 11 (after S7.1R10):
  RUN_ID=34489050155, RUN_NUMBER=11
  HEAD=3c5971c806584e32033b8ea44395fa073a74aaab
  RESULT=FAILURE - failure_stage=installer_timeout (qemu_exit_status=124,
  qemu_elapsed_seconds=6600).

  Historical stable-seed comparison (RUN_7_ONLY_OUTLIER=PROVEN_FALSE):
    Run #6  ~557.5s        (normal)
    Run #7  ~3044s         (pathological)
    Run #8  ~450s          (normal)
    Run #9  ~399s          (normal)
    Run #10 ~467.5s        (normal)
    Run #11 ~3943s         (pathological)

  PROVEN, this run: real, given evidence shows a genuine 3-attempt
  snapd.seeded lifecycle (attempt 1 ~454.619s->~622.204s fail;
  attempt 2 ~1881.540s->~2693.021s fail; attempt 3 ~2959.030s->
  ~4397.845s SUCCESS) - a desktop-security-center configure-hook
  sanity-timeout failure (~1062.944s->~1108.681s, "Change 1" per the
  given evidence), a real mass RemoveSnapServices sequence
  (~1118.784s onward), a `/snap/snapd/current` missing window
  (~1895.777s), and eventual real stable recovery (ubuntu-desktop-
  bootstrap/subiquity-server restored ~4378.547s, snapd.seeded
  finally succeeding ~4397.845s) before Subiquity/curtin ever started
  - TOTAL_UNSTABLE_SEED_WINDOW≈3943.226s (≈65m43s).

  R9's firmware-notifier QA-only mitigation continued to work - the
  599-restart storm did NOT recur.

  DESKTOP_SECURITY_CENTER_HOOK_FAILURE=PROVEN,
  SANITY_TIMEOUT=PROVEN, SNAPD_SERVICE_STARTUP_TIMEOUTS=PROVEN,
  SNAPD_SERVICE_RESTARTS=PROVEN, REMOVE_SNAP_SERVICES_SEQUENCE=PROVEN,
  MASS_SNAP_SERVICE_REMOVAL=PROVEN, /snap/snapd/current_MISSING=PROVEN,
  SNAPD_FINAL_STABLE_SEED_SUCCESS=PROVEN.
  HOOK_FAILURE_TO_UNDO_ROLLBACK_RELATIONSHIP=STRONGLY_SUPPORTED (the
  hook failure and the RemoveSnapServices/current-missing/restoration
  sequence occur in immediate temporal succession, consistent with a
  snapd Change-undo path, but NOT_PROVEN in the strict sense - this
  environment has no raw serial log or snapd Change/Task API access
  to directly confirm an explicit "Undo"/"Undoing" state transition).
  DESKTOP_SECURITY_CENTER_IS_SOLE_ROOT_CAUSE=NOT_PROVEN,
  SNAPD_HOLD_IS_ROOT_CAUSE=NOT_PROVEN, NTP_IS_ROOT_CAUSE=NOT_PROVEN,
  TCG_IS_ROOT_CAUSE=NOT_PROVEN, NETWORK_IS_ROOT_CAUSE=NOT_PROVEN - none
  promoted from inference to proof.

  PATHOLOGY_SCOPE=LIVE_INSTALLER_ENVIRONMENT_ONLY (STRONGLY SUPPORTED,
  not directly proven from a raw log this environment lacks): a
  full-repository search confirms ZERO Serein code (as opposed to
  forensic-comment/docstring mentions of OBSERVED evidence) creates,
  configures, or depends on `desktop-security-center`,
  `snapd.hold.service`, `ubuntu-desktop-bootstrap`, or
  `RemoveSnapServices` - these are entirely part of Ubuntu's own
  stock live-ISO desktop-bootstrap snap ecosystem, activated by the
  LIVE session itself (independently of, and concurrently with,
  Subiquity/curtin's own install work), never something Serein
  introduces, configures, or that persists into the installed
  target's own first-boot context (S7.2's own first-boot
  provisioning is a completely separate systemd/session context that
  never re-runs the live-ISO's casper-specific configure hooks).

  QA_ONLY_MITIGATION_ACCEPTABLE=false this round: the S7.1R9-R10-style
  QA-only kernel-token masking approach requires PROVING a specific,
  narrow, deterministic trigger for the pathological Change before it
  can be safely neutralized (Section 10's 9-point checklist,
  particularly QA_ONLY_SCOPE and a genuine causal understanding of
  WHAT starts the Change) - this environment has no raw serial log,
  no snapd Change/Task API access, and no local real-QEMU
  reproduction capability (LOCAL_REAL_QEMU=BLOCKED, as in every prior
  round) to establish that proof. Per this corrective's own explicit
  decision principle, a forensics-only pass that does not hide the
  pathology behind a speculative, unproven workaround is preferable
  to an unsafe one - QA_ONLY_SNAP_MITIGATION_IMPLEMENTED=false.

  S7.1R11 fixes (forensics-only, no snap-lifecycle mitigation):

  1. Fixed a real, PROVEN `snapd_seeded_success` false-positive: the
     old pattern (`Finished snapd\.seeded|Reached target.*Cloud-init`)
     could match a GENERIC, UNRELATED `Reached target Cloud-init...`
     systemd boot-target line as if it were a real snapd.seeded
     success - Run #11's own derived output wrongly reported
     `snapd_seeded_success≈984.407227` while the real, final, stable
     `Finished snapd.seeded.service` event was at ≈4397.845s. Fixed:
     narrowed to ONLY `Finished snapd\.seeded` - never inferred from
     any later, unrelated boot-target reached-event.
  2. Added a genuine multi-attempt seed-lifecycle model
     (`_extract_seed_attempts`) - a single, chronological state
     machine over every real "Starting snapd.seeded.service"/
     "Finished snapd.seeded.service"/snapd.seeded-failure line,
     emitting `seed_attempt_<n>_start`/`_finish`/`_result` for
     however many real attempts actually occurred (`seed_attempt_count`,
     never hardcoded), `final_stable_seed_success` (the LAST attempt's
     own finish timestamp, but ONLY if that last attempt's own result
     is "success" - so an earlier, non-final success can never be
     mistaken for the stable end of the lifecycle, exactly the real
     Run #7/#11 proof pattern), and `unstable_seed_window_duration`
     (first attempt's start -> final_stable_seed_success) - reproduces
     the given Run #11 evidence's own
     `TOTAL_UNSTABLE_SEED_WINDOW≈3943.226s` essentially exactly via a
     synthetic fixture built from the task's own given evidence.
  3. Added `snapd_hold_finish` (captured as a plain forensic data
     point only - this script never asserts or implies causality for
     it), `snap_removal_last` and `snap_removal_event_count` (an
     honest RAW LINE-MATCH count, never claimed to be a verified count
     of distinct affected snap names, which this script has no
     reliable way to determine from timestamps/patterns alone).

  Explicitly NOT done this pass: QEMU timeout (6600s) and job timeout
  (270min) both UNCHANGED - Run #11 spent ~3943s in an abnormal snap
  lifecycle before meaningful installer progress, so it did NOT
  fairly test whether 6600s is sufficient for the normal Run #10-like
  path; changing either timeout now would hide the real pathology
  behind a larger number rather than address it.
  R11_QEMU_TIMEOUT_CHANGED=false, R11_JOB_TIMEOUT_CHANGED=false. No new
  QA-only snap-lifecycle mitigation implemented (see
  QA_ONLY_MITIGATION_ACCEPTABLE=false above). Firmware-notifier QA
  mask, snapd/snap-seeding behavior, storage semantics, target fixture
  size, autoinstall activation, and primary/secondary failure-recorder
  scripts all unchanged.
```

## Real Layer-B validation status (S7.1R10)

**Ten real Installer Layer-B runs have occurred.** Run #10
(RUN_ID=34432290533, ARTIFACT_ID=10137243534) proved the R9
firmware-notifier mitigation worked and reached the furthest of any
run so far - real Subiquity postinstall entering and real
`unattended-upgrades` actually starting (~5131.64s) - before the
5400s QEMU timeout killed it with only ~268s of margin remaining:

```text
Run 10 (after S7.1R9):
  RUN_ID=34432290533, RUN_NUMBER=10
  HEAD=fd1d5a3d6483b03e2cd489e9a3c6bfaaf977c053
  RESULT=FAILURE - failure_stage=installer_timeout.

  PROVEN (locked, re-confirmed): protected disk readonly/topology
  unchanged, primary/secondary failure semantics correct.

  PROVEN, new this run:
    - R9_FIRMWARE_NOTIFIER_MASK_RUNTIME_EFFECT=PROVEN_PASS - the
      systemd.mask=snap.firmware-updater.firmware-notifier.service
      boot parameter was actually loaded, and the Run #9 restart
      storm (>=599 restarts) did NOT recur. This rules out the storm
      as an ongoing cause.
    - snapd seeding was normal this run (~423.5s -> ~891.1s,
      duration ~467.53s) - not the current blocker
      (CURRENT_SNAPD_SEED_BLOCKER=false).
    - Real curtin partitioning (~2137.9s->2252.3s), extract
      (~2268.1s->3470.3s), and curthooks (~3520.9s->4962.3s) all
      completed successfully - the furthest real curtin progress any
      run has proven.
    - Subiquity postinstall entered (~4962.8s) and real
      unattended-upgrades actually launched
      (run_unattended_upgrades ~5112.3s, `chroot /target
      unattended-upgrades -v` ~5127.0s, active ~5131.6s) - with NO
      fatal error observed before the 5400s timeout killed QEMU.
      INSTALLER_ACTIVE_AT_TIMEOUT=PROVEN,
      5400_SECOND_TIMEOUT_SUFFICIENT=PROVEN_FALSE.
    - The milestone parser still had one narrow real defect: a
      duplicate serialized representation of the SAME semantic
      snapd-startup-timeout event (identical timestamp
      597.856803s) was counted as TWO separate ordinal occurrences,
      populating both `snapd_first_startup_timeout` and
      `snapd_second_startup_timeout` with the same value.

  S7.1R10 fixes:

  1. Objective A: the R9 firmware-notifier mitigation is proven
     working and left entirely unchanged - with the storm ruled out,
     Run #10's real timeout evidence (only ~268s of margin once
     unattended-upgrades actually started) is now direct proof the
     real postinstall stage itself needs more time than 5400s
     provides. QEMU install timeout increased 5400s -> 6600s
     (110 min), still fail-closed via `timeout --signal=TERM`, never
     unbounded, never retried.
     6600_SECOND_TIMEOUT_SUFFICIENT=NOT_OBSERVED - Run #11 is the
     real test, not assumed from this change.
  2. Objective B: job-level workflow timeout increased 240 -> 270
     minutes, budgeted explicitly (~80 min worst-observed pre-install
     + 110 min real QEMU install + <=10 min x2 independently-bounded
     boot checks + ~15 min inspection/hashing/evidence/upload/closure
     + ~25 min CI variance reserve ~= 250 min, rounded to 270 min) -
     the task's own stated ceiling for this corrective, still well
     under GitHub's 360-min ceiling. Neither boot check's own
     independent bound was weakened or removed.
  3. Objective C: `_nth_valid_timestamp_from_lines` (added S7.1R9)
     counted every content-matching line with a valid timestamp as a
     distinct ordinal occurrence, even when two lines were different
     SERIALIZED REPRESENTATIONS of the exact same real semantic event
     (same parsed timestamp). Fixed with a conservative semantic
     identity rule: a candidate is only treated as a NEW ordinal
     occurrence if its parsed timestamp differs from the immediately
     preceding counted occurrence's timestamp - two lines sharing a
     timestamp are treated as one event, while two genuinely distinct
     events at different timestamps (even a millisecond apart) still
     count separately, and two unrelated event classes that happen to
     collide on a timestamp are never conflated across different
     milestone patterns (each milestone's own pattern already scopes
     the search to lines describing that one specific event class -
     this fix only changes counting WITHIN one milestone's own
     matches, never across milestones). RAW_SERIAL_LOG remains the
     one authoritative source; this parser is a non-authoritative
     forensic convenience only, never a Layer-B gate.

  Explicitly NOT done this pass: firmware-notifier mask unchanged (
  proven working, never broadened to production); snapd/snap-seeding
  behavior unchanged (not the current blocker); unattended-upgrades/
  APT/network/DNS/NTP configuration unchanged; storage semantics,
  target fixture size, partition layout, GRUB/kernel-install logic
  all untouched (Run #10 proved these already work); target-layout-
  inspector and both boot-check scripts left unmodified (no new
  evidence of a defect).
```

## Real Layer-B validation status (S7.1R9)

**Nine real Installer Layer-B runs have occurred.** Run #9
(RUN_ID=34371427617) reached the furthest of any run so far - real
curtin curthooks completing (~5049.98s), Subiquity postinstall
entering (~5050.86s), and real unattended-upgrades actually starting
(~5320.23s) - before the 5400s QEMU timeout killed it with only ~80s
of margin remaining:

```text
Run 9 (after S7.1R8):
  RUN_ID=34371427617, RUN_NUMBER=9
  HEAD=a28c9e46200913852f724a08cb2f207e23827bfc
  RESULT=FAILURE - failure_stage=installer_timeout.

  PROVEN (locked, re-confirmed): protected disk container/logical/
  both sentinels unchanged, modification count 0. Primary/secondary
  failure semantics correct. R8's QA-credential fix held.

  PROVEN, new this run:
    - Real destructive curtin execution all the way through
      curthooks completion (~5049.98s), well past R8's own furthest
      point (curthooks BEGINNING at ~3323.9s).
    - Subiquity postinstall entered (~5050.86s) and real
      unattended-upgrades actually started (~5296.87s/~5320.23s) -
      the first real evidence any run reached this far.
    - A pathological restart storm of
      snap.firmware-updater.firmware-notifier.service - >=599
      observed restarts from ~3730.94s onward, each failing with
      "Sorry, home directories outside of /home needs configuration."
      - a known, real Ubuntu snapd home-dirs-confinement message tied
      to the LIVE installer session, never anything Serein's own code
      introduces (confirmed: zero repository references to
      firmware-updater/firmware-notifier outside this one
      corrective).
    - R8's milestone parser (`extract-bootstrap-milestones.sh`) was
      STILL partially defective:
      R9_MILESTONE_PARSER_ACCURACY=PARTIAL_FAIL.

  S7.1R9 fixes:

  1. Objective A: `snap.firmware-updater.firmware-notifier.service` is
     part of Ubuntu's own stock desktop snap set (present on the base
     ISO before Serein ever touches it), and its real failure mode is
     a documented live-session/installer-environment artifact of
     snapd's confinement home-dirs check - not a defect in the
     eventually-installed target (the real end user's real `/home` is
     correctly configured; only this notifier's live-session autostart
     entry is affected). Neutralized QA-install-boot-session-ONLY via
     a new `systemd.mask=snap.firmware-updater.firmware-notifier.service`
     kernel parameter, added through the same already-proven,
     generalized kernel-token mechanism as R3's `autoinstall`/R5's
     journald-forwarding/R7's debug-logging tokens
     (`serein.installer.isoprep._mask_firmware_notifier_on_qa_entry`).
     `systemd.mask=` is a real, documented systemd kernel
     command-line option that masks a unit for THIS BOOT ONLY, purely
     in-memory - never touches the installed target's package set or
     unit files, never touches the production boot entry, never
     disables firmware-update functionality on the shipped Serein
     product.
  2. Objective B: `extract-bootstrap-milestones.sh` had ONE remaining
     real root cause across all its extraction helpers
     (PROVEN): every helper took the unconditional FIRST content
     match and only THEN tried to extract a timestamp
     (`grep -m1`/`head`-truncated before any timestamp check) - a
     real, untimestamped splash/console-duplicate line matching a
     milestone's pattern BEFORE any real, timestamped occurrence
     masked that later, real occurrence entirely
     (`snapd_seeded_first_start` came back empty despite a real,
     later, timestamped ``[379.857234] Starting snapd.seeded.service``
     line existing in the log). Fixed: every extraction helper now
     searches ALL matching lines and returns the first (or Nth) one
     that actually HAS a parseable timestamp, skipping timestamp-less
     candidates entirely (this also correctly prevents a
     timestamp-less duplicate line from ever consuming a real event's
     Nth-occurrence ordinal slot). A `pipefail` regression introduced
     while writing this fix (the new per-line reader always exits 0,
     but a genuinely-empty `grep` upstream still poisons the pipeline
     under `pipefail`, since it is "last non-zero stage", not merely
     "last stage") was caught and fixed in the same pass, restoring
     the required `|| true` on every outer extraction pipeline.
     Verified against a synthetic reproduction of Run #9's own proven
     defect shape. RAW_SERIAL_LOG remains the one authoritative
     source; this parser is a non-authoritative forensic convenience
     only, never a Layer-B gate.
  3. Objective C: Run #9's real observed timing (job start
     ~15:37:17 UTC, QEMU start ~16:57:46 UTC - ~80.5 min pre-QEMU,
     ~68 min of that spent fetching the pinned base image - QEMU end
     ~18:27:54 UTC, job end ~18:31:38 UTC - ~174 min total, even
     though the run never reached ANY downstream closure step)
     proved R8's 180-minute job-level timeout was ALSO too tight.
     Increased to 240 minutes with explicit, evidence-based budget
     arithmetic in the workflow's own comment (~80 min worst-observed
     pre-install + ~90 min real QEMU install + <=10 min each for two
     independently-bounded boot checks + ~15 min inspection/hashing/
     evidence/upload/closure + ~25 min CI variance reserve = ~230 min,
     rounded to a comfortably bounded 240 min) - still well under
     GitHub's own 360-min ceiling.
  4. Objective D: real QA-install QEMU timeout KEPT at 5400s this
     pass, not increased further. Rationale: a safe, narrowly-scoped
     QA-only corrective for the firmware-notifier storm was found and
     applied (Objective A), and that storm plausibly consumed real
     scheduling/CPU resources during exactly the window
     (~3730.94s-5400s) that ultimately starved unattended-upgrades of
     its remaining ~80s of margin. Run #10 is the real empirical test
     of whether removing that contention is sufficient - not a claim
     that 5400s is proven sufficient; if Run #10 again times out with
     the storm gone, that is new, clean evidence a real
     (non-contention) increase is needed next.

  Explicitly NOT done this pass: snapd/snap-seeding behavior
  unchanged; storage semantics untouched; target fixture stays 16G;
  autoinstall activation and R7 debug logging unchanged;
  target-layout-inspector and both boot-check scripts re-audited
  statically (confirmed byte-for-byte unchanged since before R8, and
  their partition-type/UEFI-topology logic remains disk-size-
  independent) with no defect found, left unmodified;
  `firmware-updater` itself is never removed from Serein, and no
  firmware-update functionality is disabled on the installed target -
  only the ONE pathological live-session restart loop is masked, on
  the QA boot entry only.
```

## Real Layer-B validation status (S7.1R8)

**Eight real Installer Layer-B runs have occurred.** Run #8 reached
real curtin destructive execution against the explicit target
(partitioning, ESP/root formatting, extract, curthooks, EFI package
install, kernel package install starting) - the furthest any real run
has progressed - but was again terminated by the global timeout while
actively working:

```text
Run 8 (after S7.1R7):
  RUN_ID=34355674598, RUN_NUMBER=8
  HEAD=bc614c171d95e6b670ed88b948583b81a61d769d
  RESULT=FAILURE - failure_stage=installer_timeout.

  PROVEN (locked, re-confirmed): protected disk container/logical/
  both sentinels unchanged, modification count 0. R7's primary/
  secondary failure-semantics fix worked correctly at runtime.

  PROVEN, new this run:
    - snapd.seeded took only ~450.33s this run (vs. Run #7's
      ~3044s) - confirming RUN_7_EXTREME_SNAPD_CHAIN_REPRODUCED=false;
      the extreme chain is not a permanent defect, just real run-to-
      run variance.
    - Real destructive curtin execution against the explicit target:
      old storage cleared, ESP created/formatted, root created/
      formatted (~1894.6s->2081.1s), a full extract phase
      (~2107.5s->3268.4s, ~1161s), curthooks beginning (~3323.9s),
      EFI package install completing (~3487.6s), kernel package
      install starting (~3561s) - all still actively progressing when
      the 3600s timeout killed QEMU. 3600S_TIMEOUT_SUFFICIENT=PROVEN_FALSE.
    - R7's milestone parser (`extract-bootstrap-milestones.sh`) had
      four real accuracy defects: R7_MILESTONE_PARSER_ACCURACY=PARTIAL_FAIL.

  S7.1R8 fixes:

  1. Objective A: real QA-install timeout 3600s -> 5400s (90 min) -
     direct evidence of continuous progress right up to the previous
     deadline, never merely because the run failed. An explicit,
     bounded job-level `timeout-minutes: 180` was also added (the
     workflow previously relied on GitHub's own much larger 360-minute
     default) - see the workflow's own comment for the real budget
     reasoning (~30 min pre-install + 90 min install + ~25 min
     post-install, rounded up with real margin).
  2. Objective B: `extract-bootstrap-milestones.sh` - fixed four real
     defects (a genuine, root-cause-identified `pipefail` bug was also
     found and fixed while doing so - see the script's own header):
     - Defect 1: `snapd_seeded_first_start` was OMITTED (not wrong) -
       the timestamp extractor required kernel-style `[NNN.NNNNNN]`
       brackets, but systemd-journal-forwarded lines (most of what
       this script needs) may use a bare, unbracketed format. Fixed
       to accept both.
     - Defect 2: one real timeout event was double-counted as both
       `snapd_first_startup_timeout` and `snapd_second_startup_timeout`
       - the old pattern's `Failed to start` alternative matched a
       SEPARATE journal line systemd emits for the SAME single event.
       Narrowed to one canonical, specific message per real event.
     - Defect 3: an AppArmor profile-load announcement (whose PROFILE
       NAME happens to contain both "desktop-security-center" and
       "hook") was misclassified as a real hook failure. Replaced with
       a real, two-stage semantic match requiring an explicit failure/
       error term and excluding profile-load announcement lines.
     - Defect 4: generic snap activity was at risk of being
       misclassified as Run #7's real mass-removal sequence. Narrowed
       to the one specific, real snapd internal task-kind name
       (`RemoveSnapServices`) Run #7's own evidence actually showed.
     All four fixes verified against a synthetic reproduction of Run
     #8's own reported timeline - reproduces
     `snapd_seed_duration=450.33` exactly. RAW_SERIAL_LOG remains the
     one authoritative source; this parser is a non-authoritative
     forensic convenience only, never a Layer-B gate.
  3. Objective C: a real, reproduced (not merely theorized) root cause
     for the intermittent CI credential test flake -
     `secrets.token_urlsafe(24)` can generate a password beginning
     with `-` (the base64url alphabet includes it), and without an
     explicit end-of-options marker, `openssl passwd`'s own CLI parser
     misinterpreted that leading-`-` password as an unknown option,
     exiting non-zero. Never a timeout (every real local invocation
     completed in well under 200ms). Reproduced directly (2 failures
     in 200 real local invocations, always this exact stderr) and
     fixed with the POSIX `--` end-of-options marker - verified
     against 500 further real invocations (10 genuinely leading-
     hyphen) with zero failures.

  Explicitly NOT done this pass: snapd/snap-seeding behavior
  unchanged (Run #8 disproved the "permanent defect" hypothesis);
  storage semantics untouched (target fixture stays 16G; Run #8
  proved real destructive execution against the explicit target
  works); autoinstall activation and R7 debug logging unchanged;
  target-layout-inspector and boot-check scripts re-audited statically
  (partition-type/UEFI-topology logic, size-independent) with no
  defect found, left unmodified.
```

## Real Layer-B validation status (S7.1R7)

**Seven real Installer Layer-B runs have occurred.** Run #7 reached
real curtin execution (`python3.12 -m curtin --showtrace -vvv`, real
`apt-config` start) but was dominated by a ~3044s pre-Subiquity
bootstrap window:

```text
Run 7 (after S7.1R6):
  RUN_ID=34335197624, RUN_NUMBER=7
  HEAD=4d38f09e21d133a3c47330a25d20d0d81ad10747
  RESULT=FAILURE - failure_stage=installer_timeout (real primary
  blocker; NOT artifact_release_failed, though a real defect made the
  latter briefly ABLE to occupy that slot - see below).

  PROVEN (locked, re-confirmed, not reopened):
    - R4's readonly=on + R5's hash-disk-image.sh: protected container/
      logical/both sentinels unchanged.
    - R3's autoinstall activation and R6's real curtin execution.

  PROVEN, new this run: snapd.seeded took ~3044s (437.54s->3481.79s) -
  vs. Run #6's ~557.5s - dominated by real, observed snapd service
  startup timeouts and restarts (at least two full cycles), a
  desktop-security-center configure-hook failure + snapd sanity
  timeout (~1047s), a mass snap service-removal/remount sequence
  (~1068s onward), a task referencing a missing /snap/snapd/current
  (~1516s), and a real NTP 10-minute wait (~3474s) before snapd.seeded
  finally completed. Curtin then had only ~19-21s of real runtime
  before the 3600s global timeout killed QEMU.
  WHY_RUN_7_SNAPD_SEEDED_TOOK_~3044s=NOT_PROVEN - this remains
  genuinely unknown; do not treat snapd, TCG, NTP, or
  desktop-security-center individually as the sole proven cause.

  SEPARATELY PROVEN: R6's own secondary-failure wiring had a real
  defect - all 8 "secondary, non-blocking" call sites called BOTH the
  PRIMARY recorder (distribution/scripts/record-failure.sh) AND the
  new secondary recorder for the SAME event, meaning a non-blocking
  cleanup failure (e.g. release-artifact.sh failing for
  build/work/extracted) COULD occupy dist/.failure_stage before the
  real installer blocker occurred, if it happened chronologically
  first. Run #7 showed exactly this: a build/work/extracted release
  failure (reported permission-denied class error - the EXACT
  errno/message could not be reconfirmed from this environment, see
  ARTIFACT_RELEASE_PERMISSION_ROOT_CAUSE below) occurred before the
  real install step.

  S7.1R7 fixes/instruments:

  1. Objective B (the concrete, provenwiring defect): all 8 secondary
     call sites now call ONLY installer/scripts/record-secondary-failure.sh,
     never distribution/scripts/record-failure.sh - a secondary/non-
     blocking operation must never invoke the primary recorder. The
     genuinely-primary call sites (disk_preflight, base_fetch, the
     real install run, target layout inspection failure, etc.) are
     unchanged and still call the primary recorder as before.
  2. Objective A (bootstrap forensics): TWO safe, zero-guest-risk-of-
     breakage additions:
     - `installer/scripts/extract-bootstrap-milestones.sh` (new) -
       purely host-side, bounded parsing of the ALREADY-CAPTURED serial
       log (already rich in detail thanks to R5's
       systemd.journald.forward_to_console=1 fix) into a compact,
       machine-readable milestone/duration record
       (qa-install-bootstrap-milestones.env) - snapd_seed_duration,
       curtin_runtime_before_qemu_exit, etc., for real run-to-run
       comparison. Verified against a synthetic reproduction of Run
       #7's own reported timeline (real test fixture, not invented
       numbers) - reproduces snapd_seed_duration=3044.25 and
       curtin_runtime_before_qemu_exit=21.00 exactly.
     - `systemd.log_level=debug` added to the QA-install boot entry
       (chained onto the same, already-proven kernel-parameter
       mechanism as `autoinstall`/journald-forwarding) - surfaces more
       systemd job/unit-timeout reasoning without any new guest-side
       file/service/transport.
     Deliberately NOT implemented this round (real risk/benefit
     tradeoff, explicitly documented): live in-guest command execution
     (`snap changes`/`snap tasks`, structured `systemctl show` field
     dumps, `timedatectl`, `ip route`) would require injecting a NEW
     systemd unit into the live ISO's squashfs tree - a materially
     larger, untestable-in-this-environment change with real risk of
     breaking the NEXT boot in a NEW way if done wrong (this
     environment has no real xorriso/squashfs/QEMU to validate such a
     change against). Deferred rather than risked without real testing
     capability.

  Explicitly NOT done this pass: timeout unchanged (3600s); snapd/
  snap-seeding not disabled, masked, or worked around; storage
  semantics untouched (Run #7 provided no evidence of a storage
  regression); target fixture size unchanged (16G); no permission/
  ownership change to release-artifact.sh or its callers -
  ARTIFACT_RELEASE_PERMISSION_ROOT_CAUSE=NOT_PROVEN (code inspection
  confirmed S7.0's own xorriso-based extraction that creates
  build/work/extracted never uses sudo anywhere, so no plausible
  root-ownership mechanism was found in this repository's own code -
  but the exact real OS-level error could not be reconfirmed from the
  raw Run #7 log, which was not available to this environment; only
  the recorder-semantics defect was fixed).
```

## Real Layer-B validation status (S7.1R6)

**Six real Installer Layer-B runs have occurred.** Run #6 is the
furthest any real run has ever progressed - both R4's readonly hardening
and R3's autoinstall activation are now PROVEN correct, and real
Subiquity/curtin execution was directly observed for the first time:

```text
Run 6 (after S7.1R5):
  RUN_ID=34265949262, RUN_NUMBER=6
  HEAD=7dab8b650fabbd9f56d6ec94b45797f102951bf4
  RESULT=FAILURE - failure_stage=installer_timeout, but NOT a stall.

  LOCKED PROVEN PASS (re-confirmed, not reopened):
    - protected_container_sha256 unchanged, protected_logical_sha256
      unchanged, both protected sentinels unchanged (R4's readonly=on
      fix + R5's hash-disk-image.sh both proven correct at runtime)
    - autoinstall kernel token present, Subiquity started, autoinstall
      config extracted/loaded/core-validated/applied, Subiquity
      entered its real Install phase (R3's fix proven to actually
      trigger the full activation chain, not merely the kernel token)
    - REAL curtin execution: `python3.12 -m curtin --showtrace -vvv`,
      real chroot/apt/dpkg/debconf activity observed as late as
      ~1769s - only ~31s before the previous 1800s deadline killed it

  This is the first real evidence that QEMU was terminated WHILE the
  installer was actively progressing, not stalled - the first
  evidence that genuinely authorizes a timeout increase (never merely
  because a run failed).

  S7.1R6 fixes/instruments:

  1. Real QA-install timeout: 1800s -> 3600s (installer/scripts/
     run-qa-install.sh's own default, and the workflow's explicit
     --timeout). Every OTHER timeout (bounded startup probe,
     installed-target boot check) is a separate, already-bounded
     scope, deliberately left unchanged.
  2. Target fixture capacity: 8G -> 16G
     (installer/scripts/create-fixture-disks.sh) - real project
     evidence (this document's own QA_ISO_GIB=7 estimate for Serein's
     built Ubuntu 26.04 Desktop QA ISO; ~6.0 GB base ISO per
     distribution/base-image.json's own recorded notes) meant the
     previous 8G target left essentially no real margin for a
     decompressed full-desktop install. Protected fixture size (4G)
     is unchanged - independently justified, never grown merely
     because target did.
  3. installer/scripts/inspect-target-layout.sh rewritten to remove
     its qemu-nbd/nbd-device-node dependency (the same class of defect
     R5 already proved fragile in the sibling hash-disk-image.sh) -
     this script had never actually executed successfully in any real
     run (every prior run timed out before reaching it), and Run #6's
     real curtin progress makes Run #7 newly likely to finally reach
     it. Also fixed a real, independently-found gap: the root-partition
     mount previously lacked `noload`, risking an ext4 journal replay
     even under a read-only mount.
  4. Primary/secondary failure-stage semantics: new
     installer/scripts/record-secondary-failure.sh + a new,
     purely-additive `secondary_failures` evidence field, so every
     diagnostic/cleanup step's own failure remains visible without
     ever being able to overwrite (or be confused with) the real
     primary blocker - which remains computed exclusively by
     `distribution/scripts/record-failure.sh` (S7.0-owned, unmodified).

  Preflight arithmetic revised (Section 8-9 of storage-lifecycle.md):
  FIXTURE_QCOW2_VIRTUAL_GIB 12->20 (documentation/contrast only) and
  FIXTURE_QCOW2_ALLOCATED_GIB 6->12 (Run #6's real curtin progress
  justifies a more generous real-allocation estimate) - REQUIRED_GIB
  stays 27 unchanged, since ISOPREP_PEAK_GIB=21 remains the binding
  constraint either way.

  This pass deliberately did NOT: touch storage-selection/curtin-
  grammar/target-identity code (Section 12's "block_probe_fail" was
  observed but not proven fatal - installer activity continued
  afterward to ~1769s, so it was left untouched), weaken any safety
  invariant, or claim closure - the exact reason installation does not
  complete within the new 3600s budget remains genuinely unknown
  pending Run #7's real evidence.
```

## Real Layer-B validation status (S7.1R5)

**Five real Installer Layer-B runs have occurred.** Run #5 confirmed
BOTH the R3 boot-entry fix and the R4 protected-disk readonly
hardening work at runtime, and moved the causal boundary one level
deeper - the R4 root cause is CLOSED:

```text
Run 5 (after S7.1R4):
  RUN_ID=34255177947, RUN_NUMBER=5
  HEAD=978099b78c4d758b4773c531b104c80ef871f9fe
  RESULT=FAILURE.

  PROVEN PASS (locked, not reopened):
    - autoinstall kernel token present (R3's fix, re-confirmed)
    - protected_disk_hash_unchanged=true,
      protected_disk_modification_count=0,
      protected_esp_unchanged=true (R4's readonly=on fix WORKS - the
      protected container hash is now genuinely stable across a real
      run, resolving the exact defect Run #3 and Run #4 both showed)

  PROVEN FAIL:
    - "Hash protected disk (pre-install baseline)" - the FIRST real
      workflow failure. The exact underlying qemu-nbd/device-node
      failure could not be reproduced locally (this development
      environment has no qemu-nbd/nbd kernel module - BLOCKED), but
      nbd-based device access was the one operation in that script
      with no precedent of PROVEN success anywhere else in this
      repository (create-fixture-disks.sh's nbd0/nbd1 usage IS proven
      by every run reaching fixture creation; nbd2/nbd3 usage -
      inspect-target-layout.sh, and the original
      hash-protected-disk.sh - had never actually executed
      successfully in any real run before this failure). This step's
      own failure was ALSO invisible to the evidence/closure system -
      unlike every other failure-capable step in this workflow, it
      never called `record-failure.sh` at all.
    - qemu_exit_status=124 (installer_timeout, the wrapper's own 1800s
      budget), installer_userspace_reached=true - matches Run #4's
      pattern exactly; the real installer still does not complete.
    - target qcow2 CONTAINER hash changed
      (860d31a3...4113 -> 16e46dba...da151), but this alone does NOT
      prove curtin ever wrote real partitions (the same container-
      vs-guest-visible ambiguity the R4 corrective already identified
      for the protected disk) - target_esp_present=false,
      target_root_present=false, installed_boot_status=not_performed,
      serein_core_present=false all remained the fail-closed defaults,
      since "Inspect target disk layout" never ran (gated on a
      successful install that never happened).

  S7.1R5 fixes/instruments:

  1. installer/scripts/hash-disk-image.sh (replaces
     hash-protected-disk.sh) - removes the qemu-nbd/nbd-kernel-module/
     device-node dependency entirely. Uses `qemu-img convert` (pure
     userspace, no root, no kernel module) to produce a temporary raw
     file for the guest-visible logical-content hash, and `losetup -P`
     (the kernel's always-built-in loop driver, never a separately
     loadable module like nbd) on that already-converted, disposable
     temp file for the two sentinel-file checks. Generalized
     (Objective D) to hash BOTH the protected AND target disks, before
     and after the install attempt, regardless of install success -
     giving real diagnostic evidence even on a stalled/timed-out
     install like Run #5. Every one of these four new hashing steps
     now also calls `record-failure.sh` on its own failure (secondary,
     non-blocking - never `exit 1`), fixing the exact invisibility
     defect Run #5 exposed.
  2. `installer/scripts/isoprep.py`'s boot-entry patching now ALSO adds
     `systemd.journald.forward_to_console=1` (Objective C) - forwards
     the systemd journal (which Subiquity-server/curtin/cloud-init, as
     ordinary systemd-managed snap services, log to by default) to the
     serial console in real time, giving the NEXT run's serial log
     actual Subiquity/curtin runtime evidence instead of only kernel/
     systemd boot messages.

  This pass deliberately did NOT: increase the 1800s timeout, modify
  target selection/storage-match/curtin-grammar code, weaken the
  protected-disk readonly hardening, or claim the exact Subiquity/
  curtin-side reason installation stalls - that remains the primary
  open question for Run #6, now with meaningfully better evidence
  infrastructure (journald forwarding + generalized before/after
  logical-content hashing for both disks) to actually answer it.
```

## Real Layer-B validation status (S7.1R4)

**Four real Installer Layer-B runs have occurred.** Run #4 confirmed
the S7.1R3 boot-entry fix works at runtime and moved the causal
boundary one level deeper - the S7.1R3 root cause is CLOSED:

```text
Run 4 (after S7.1R3):
  RUN_ID=34239853849, RUN_NUMBER=4
  HEAD=12257b49f50a28755588c0d31ff1d8b91b3f338d
  RESULT=FAILURE - failure_stage=installer_timeout.

  PROVEN: the real captured kernel command line now includes
  `autoinstall` (`BOOT_IMAGE=/casper/vmlinuz console=ttyS0,115200n8
  autoinstall --- splash`) - the S7.1R3 fix works at runtime.
  installer_userspace_reached=true; Subiquity-related services were
  observed starting. qemu_exit_status=124 (the wrapper's own 1800s
  timeout fired). Target qcow2 hash unchanged before/after (no
  installation was ever proven to complete or begin destructive work).
  Protected qcow2 hash CHANGED before/after - the SECOND consecutive
  real run showing this (Run #3 also showed it), which invalidates
  Run #3's "missing autoinstall -> live-desktop automount" hypothesis
  as a SUFFICIENT explanation, since autoinstall is now proven present
  and the mutation still occurred.

  S7.1R4 fixes/instruments (without yet knowing the exact Subiquity/
  curtin-side reason installation did not complete within 1800s -
  that remains the primary open question for Run #5):

  1. `installer/scripts/run-qa-install.sh`'s protected qcow2 backend
     is now attached `readonly=on` (previously opened read-write by
     both the bounded startup probe and the real timed run - the
     exact code-cited point, `run-qa-install.sh`'s protected `-drive
     if=none,...` line, confirmed by direct inspection, never merely
     assumed). This is architecturally correct independent of the
     exact causal mechanism - a disk that exists ONLY to prove the
     installer never touches it should never be opened for write
     access by any component - and closes off every QEMU-side write
     vector categorically (guest writes, qcow2's own internal
     lazy-refcount/dirty-bit bookkeeping on open/close).
  2. `installer/scripts/hash-protected-disk.sh` (new) separately
     measures the protected disk's container-file hash, its full
     guest-visible logical block content (via read-only qemu-nbd), and
     two real sentinel files (ESP + ext4 data) - called both
     immediately before and immediately after the real install
     attempt. This distinguishes "container bytes changed but
     guest-visible content did not" from "guest-visible content
     genuinely changed" - the existing container-hash-only measurement
     could not make this distinction. Diagnostic only - the EXISTING
     container-hash-based closure gate is unchanged and unweakened;
     these new hashes are additive evidence in a separate,
     non-gating file (`protected-disk-diagnostic.env`).
  3. `installer/scripts/extract-installer-signals.sh` (new) - a
     narrowly scoped grep of the real serial log for
     Subiquity/curtin/autoinstall/cloud-init/error lines, uploaded as
     `qa-install-subiquity-signals.log`, so a human reviewing a future
     run's evidence does not have to manually search a 400+KB raw
     transcript by hand.

  This pass deliberately did NOT: increase the 1800s timeout, modify
  target selection/storage-match/curtin-grammar code, or claim the
  exact Subiquity/curtin-side reason installation did not complete -
  those remain genuinely unknown pending Run #5's real evidence (in
  particular the new signal-extraction file and the new protected-disk
  before/after comparison).
```

## Real Layer-B validation status (S7.1R3)

**Three real Installer Layer-B runs have occurred**, each exposing and
fixing a real defect:

```text
Run 3 (after S7.1R2):
  RUN_ID=34224122883, RUN_NUMBER=4
  HEAD=957542960c849d404796ef7c1027052cdc1fe031
  RESULT=FAILURE - failure_stage=installer_timeout. R2's QEMU corrective
  is PROVEN: qemu_started=true, installer_userspace_reached=true, and
  the real guest kernel dmesg shows the intended topology exactly
  (virtio0=[vda] 4.00 GiB=protected, virtio1=[vdb] 8.00 GiB=target) -
  no drive/device swap, no /dev/vdX confusion. The QEMU process was
  killed by the wrapper's own `timeout` after the full 1800s budget
  (qemu_exit_status=124).

  PROVEN root cause (direct evidence, not inferred): the real captured
  kernel command line was exactly
  `BOOT_IMAGE=/casper/vmlinuz console=ttyS0,115200n8 --- splash` - no
  `autoinstall` token anywhere. `serein.installer.isoprep.prepare_qa_install_iso`
  wrote `autoinstall.yaml` at the extracted tree's root but never
  patched the boot entry to actually trigger unattended installation -
  the boot entry it inherits unmodified is
  `serein.distribution.qa_boot`'s own "Serein Alpha
  (qa-serial-boot-smoke)" entry, which is EXPLICITLY documented and
  coded (Section: "never add autoinstall and never touch any disk
  target") to never carry that parameter, since it exists only for
  S7.0's own read-only boot-smoke test. The medium therefore booted
  into a completely normal interactive Ubuntu Desktop live session -
  matching every other observed symptom: the full stock snap set
  loading (firefox, thunderbird, gnome-46-2404, ubuntu-desktop-bootstrap,
  ...; Serein Alpha's base is `edition: "desktop"` per
  `distribution/base-image.json`, so this alone is not evidence of a
  wrong ISO - Ubuntu Desktop DOES ship its own curtin/subiquity-server
  via the `ubuntu-desktop-bootstrap` snap, whose apparmor profiles
  visibly loaded in the serial log, but were never invoked in
  unattended mode), the target disk hash never changing (curtin was
  never told to run), and the run exhausting its 30-minute timeout
  idling in a live session that had nothing to unattend.

  Fixed by S7.1R3: `prepare_qa_install_iso` now further patches its
  OWN independent copy of the extracted tree (never
  `serein.distribution.qa_boot` itself, whose "never autoinstall"
  contract must stay intact for S7.0's boot-smoke use) to add the bare
  `autoinstall` kernel parameter to that one specific boot entry - see
  `serein.installer.isoprep._enable_autoinstall_on_qa_entry`.

  Real Run #3 also showed the protected disk's hash changed
  (`protected_disk_modification_count=1`) while the target's did not.
  INFERRED (not proven): this is a downstream symptom of the SAME root
  cause, not an independent storage-selector defect - a normal
  interactive Ubuntu Desktop live session runs `udisks2.service`
  ("Disk Manager") with automount active, and even a brief, harmless
  mount of the protected fixture's pre-existing ext4 partition
  (superblock last-mount-time/journal-replay) is a well-known way to
  produce a small hash delta with zero deliberate content change - a
  real unattended Subiquity autoinstall run explicitly does NOT load
  the full desktop/automount stack this evidence shows running. This
  is not yet proven; a real Run #4 (which will, for the first time,
  actually reach curtin/Subiquity) is the genuine test of whether it
  recurs. The protected-disk safety invariant itself
  (`protected_disk_hash_unchanged`/`protected_disk_modification_count`)
  is unchanged and unweakened by this pass - see
  `docs/installer/protected-disks.md`.
```

## Real Layer-B validation status (S7.1R2)

**Two real Installer Layer-B runs have occurred**, each exposing and
fixing a real defect:

```text
Run 1 (after S7.1 initial integration):
  RUN_ID=34216492634, RUN_NUMBER=1
  HEAD=27f144f47667c0efe493fe2212437af4ab742dad
  RESULT=FAILURE - failure_stage=disk_preflight. The original preflight
  model summed every large artifact this job ever creates as though
  they all coexisted simultaneously (55 GiB required) against a real
  ~36.4 GiB available (FREE_SPACE_AFTER_CLEANUP_KB=38180984,
  AVAILABLE_KB=38180956). Fixed by S7.1R - see
  docs/installer/storage-lifecycle.md for the real per-asset lifecycle
  analysis and the corrected, real-simultaneous-residency preflight
  model (REQUIRED_GIB=27).

Run 2 (after S7.1R):
  RUN_ID=34219273003, RUN_NUMBER=2
  HEAD=6b9b04155f060a135a7bab0a8a12b26cdd58644a
  RESULT=FAILURE - failure_stage=install_failed. The corrected S7.1R
  storage model is PROVEN: disk_preflight/base_fetch/base_verify/
  production_iso_build/production_iso_inspection/qa_iso_build/
  qa_iso_inspection/autoinstall_render/qa_install_iso_prepare/
  protected_qcow2_created/target_qcow2_created/fixture_topology_verified
  all PASSED for real. The real QA autoinstall QEMU run itself then
  failed - protected/target disk hashes were unchanged before/after
  (protected_disk_modification_count=0, target_disk_changed=false),
  meaning no evidence exists that the installer ever reached
  destructive target-disk work. `qa-install-serial.log` alone did not
  carry enough diagnostic evidence to determine why. High-confidence
  causal hypothesis (never confirmed against the real exact stderr,
  which this run did not separately retain - RUN_2_EXACT_QEMU_STDERR=
  NOT_RETAINED): `run-qa-install.sh`'s legacy
  `-drive if=virtio,...,serial=...` convenience shorthand is a known
  QEMU compatibility hazard - the shorthand does not reliably plumb
  `serial=` through to the device model on every QEMU version. Fixed
  by S7.1R2 - see docs/installer/vm-validation.md's "QEMU startup
  evidence" section for the corrected modern split backend/device
  topology, the new bounded startup probe, and the new precise
  qemu_startup/installer_timeout/installer_execution failure
  classification (replacing the old, undifferentiated
  `install_failed`) that a third run will need to make full use of.
```

Because Run 2 failed inside the real QEMU install step, nothing past
it was exercised: `REAL_INSTALLER_EXECUTION`,
`REAL_PROTECTED_DISK_HASH_PROOF`, `REAL_TARGET_LAYOUT_INSPECTION`, and
`REAL_INSTALLED_BOOT` are all still `NOT_OBSERVED` for a corrected
run - Run 2 is evidence of the QEMU-drive-identity defect S7.1R2
fixes, never evidence that the real destructive install itself works.
Run 2 also exposed two secondary, non-causal release/cleanup step
failures (execution continued into the real install attempt
regardless) - their exact root cause is likewise `NOT_RETAINED`
(no `gh` CLI access from this development environment to inspect the
real job log); S7.1R2 hardened every `Release ...` step to record a
real, first-failure-wins-safe `artifact_release_failed` stage on any
future recurrence (visible in evidence, never silently swallowed)
without ever masking the real causal blocker or aborting the job over
a best-effort cleanup step.

Run 1's evidence-fidelity defect (`target_explicit`/
`target_identity_revalidated`/`target_disk_attached` recorded as
`true` unconditionally even though disk_preflight failed before any of
those stages could possibly have run) remains fixed as of S7.1R -
`target_disk_attached` is no longer a hardcoded structural constant,
and every one of these three fields in `installer-smoke.yml`'s
evidence-assembly step is gated on the real stage that would have
proven it.

A third real Installer Layer-B run against the S7.1R2 commit is
required before any `REAL_*` field below can honestly move past
`NOT_OBSERVED`. This development environment has no `qemu-img`/
`qemu-nbd`/`curtin`/Subiquity/`qemu-system-x86_64` installed
(`REAL_LOCAL_QEMU=NOT_AVAILABLE` - consistent with every S7.0 round of
this repository's history, see
`docs/distribution/known-limitations.md`), so `installer-smoke.yml`
itself has only ever been validated structurally and via real `bash`
execution against a stub `qemu-system-x86_64` from here:

| Field | Status | Why |
|---|---|---|
| `LAYER_A` | **PASS** | Full `pytest`/`ruff`/`mypy`/`verify.sh` against `src/serein/installer/`, `tests/test_installer.py`, and every `installer/scripts/*.sh` file (real `bash -n` syntax check, plus real `bash` execution of `run-qa-install.sh`/`release-artifact.sh` against stub tools on `PATH`). |
| `REAL_DISK_PREFLIGHT` | **PASS** (Run 2) | Proven for real - the S7.1R storage model is closed pending new contrary evidence (Section 15 of the S7.1R2 corrective). |
| `REAL_QEMU_STARTUP` | **FAIL** (Run 2, hypothesized cause) | The exact real defect this S7.1R2 pass targets. Not yet re-run for real against the corrected topology. |
| `INSTALLER_BACKEND_AVAILABLE` | **NOT_OBSERVED** | `curtin`/Subiquity not installed in this environment; `serein.installer.doctor` correctly reports `SKIP`, never a fabricated pass. |
| `REAL_INSTALLER_EXECUTION` | **NOT_OBSERVED** | Requires a real GitHub Actions run of `installer-smoke.yml` that gets past the corrected QEMU startup. |
| `REAL_TARGET_DISK_INSTALL` | **NOT_OBSERVED** | Same. |
| `REAL_INSTALLED_SYSTEM_BOOT` | **NOT_OBSERVED** | Same. |
| `PROTECTED_DISK_MODIFICATION_COUNT` | **NOT_OBSERVED** (0 in Run 2, but vacuously - the install never reached destructive work) | The hashing/comparison logic itself is unit-tested (`tests/test_installer.py::TestEvidence`), and Run 2 did hash a real qcow2 pair before/after a real (failed) run - but a modification count of 0 here is not yet a positive proof of anything, since no destructive work was ever attempted. |

Per this repository's own established closure discipline (see every
S7.0 round's final report), this document states that gap honestly
rather than fabricating success. `python -m serein.installer` and the
main `serein installer` CLI are real, tested Layer-A code; the actual
`qemu-nbd`/`parted`/`mkfs`/`curtin` shell mechanics in
`installer/scripts/*.sh` and `installer-smoke.yml` are carefully
reasoned but **unexercised** pending a real CI run - exactly the
position S7.0's `boot-smoke.sh`/`iso-smoke.yml` were in before their
first real Layer-B run, and expected to need a similar corrective
iteration once real evidence exists.

## Expected S7.1 Alpha limitations

```text
physical hardware installation      NOT_PERFORMED (Section 53)
Secure Boot                          NOT_PERFORMED
disk encryption (LUKS/TPM)           not implemented (Section 16)
RAID / LVM / ZFS                     not implemented (Section 16)
automatic dual boot                  not implemented (Section 56)
partition resize/shrink              not implemented (Section 56)
BitLocker-aware installation         not implemented (Section 56)
advanced manual partition editor     not implemented
NVMe edge cases beyond the parser    only the naming CONVENTION is
                                       tested (nvme0n1/nvme0n1p1); no
                                       real NVMe hardware/qcow2 variant
                                       has been exercised
USB bridge identity quirks           not exercised - id_path probing
                                       is a best-effort /dev/disk/by-path
                                       scan, never validated against
                                       real USB-to-SATA/NVMe bridge
                                       hardware, which is known to
                                       sometimes hide or duplicate
                                       serial/WWN reporting
```

These are legitimate, intentional deferrals - never converted into a
fake PASS.

## `openssl passwd` argv exposure (Section 35)

`serein.installer.payload.generate_qa_credential` passes the freshly
generated plaintext QA password as a command-line argument to
`openssl passwd -6`. This is visible, for the brief duration of that
one process, to anything else with process-listing access on the same
host. Accepted only because this function is intended exclusively for
the single-tenant, ephemeral Layer-B CI runner, and is never called
from any interactive or production code path (the interactive `serein`
CLI has no command that could ever reach it). A future hardening could
pass the password via `openssl passwd -stdin` instead, which the
current `serein.development.runner.CommandRunner` protocol does not
support (no stdin parameter) - deferred rather than extending that
shared protocol speculatively in this pass.

**S7.1R8 fix**: the same argv-based invocation this note describes had
a real, reproduced defect - `secrets.token_urlsafe(24)` can generate a
password beginning with `-` (the base64url alphabet includes it), and
without an explicit end-of-options marker, `openssl`'s own CLI parser
misinterpreted that leading-`-` password as an unknown OPTION rather
than the intended positional value, causing `openssl passwd` to exit
non-zero (`Unknown option: -<password>`). This was the real root cause
of an intermittent CI test failure
(`TestPayload::test_generate_qa_credential_unique_each_call`, ~1-in-64
odds per call) previously suspected to be a timeout - reproduced
directly (2 failures in 200 real local `openssl passwd -6`
invocations, always this exact stderr, never a timeout) and fixed by
inserting the POSIX `--` end-of-options marker immediately before the
password argument. Verified against 500 further real invocations
(10 genuinely leading-hyphen) with zero failures after the fix.

## Renderer schema fidelity (Section 25-26)

`serein.installer.renderer.render_autoinstall_storage_config` follows
curtin's documented "storage config version 2" action schema
(`disk`/`partition`/`format`/`mount` actions with `match`/`wipe`/
`ptable`/`grub_device`/`size`/`fstype` keys), but this has not been
validated against a real `curtin`/Subiquity invocation in this
environment - mirrors the exact caveat pattern S7.0 already applied to
its own UEFI-evidence heuristic
(`docs/distribution/upstream-installer-research.md`). If a real
Layer-B run shows Subiquity rejecting the rendered config, that is a
new, narrowly-scoped defect to fix on its own real evidence, not
something this pass could pre-empt without a real installer to test
against.

## Windows/install-media classification (Section 13)

`serein.installer.diskprobe._classify_windows` is a best-effort label/
filesystem heuristic (FAT32 + a label containing "system"/"efi" ->
`windows_efi_detected`; a label containing "recovery"/"winre" ->
`windows_recovery_detected`; any NTFS signature -> contributes to
`windows_detected`). It has never been run against a real Windows
installation's actual partition labels, which are not standardized and
can vary by Windows version, OEM, and locale. The safety invariant
(`docs/installer/protected-disks.md`) never depends on this
classification being correct - it is diagnostic/warning evidence only.

## Disk-space preflight arithmetic (Section 50)

`installer-smoke.yml`'s preflight requirement (`REQUIRED_GIB=55`) is a
documented, named-component estimate, not a measured peak - S7.0's own
preflight number was revised twice (S7.0RM, S7.0RM4) after real runs
exposed the actual peak was different from the initial estimate.
Expect the same here once a real run produces real `df`/`du` evidence.

## No physical hardware install validation this phase (Section 53)

Real installation, for this phase, means real installer execution
against real virtual block devices under QEMU. Physical external-disk
testing remains `PHYSICAL_HARDWARE_INSTALL=NOT_PERFORMED` for initial
S7.1 closure - the final end-to-end physical validation is deferred
until after the installer + firstboot + recovery chain (S7.1 + S7.2 +
S7.3) is available and explicitly reviewed (Section 54: this
implementation phase must not access or alter any real external disk).
