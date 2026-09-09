# Known Limitations (S7.1)

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
