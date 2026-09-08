# Known Limitations (S7.0; updated by the S7.0R Layer-B closure corrective; most recently S7.0RM7)

## Scope limitations (by design - Section 83)

- **Not a public release.** See
  `docs/distribution/licensing-and-release-boundary.md` - the project
  has no selected license; every artifact this phase produces is a
  private development alpha.
- **Project license unresolved.** No `LICENSE` file exists; a public
  release is blocked on the project owner making that decision, not on
  anything S7.0 could implement.
- **Installer branding not final.** S7.0 deliberately does not fork or
  re-theme the Ubuntu/Subiquity installer UI (Section 3) - it may still
  show upstream Ubuntu visuals throughout.
- **Serein payload embedded ≠ installed.** The payload manifest on
  built media (`serein/payload-manifest.json`) proves files are present
  on the medium, never that they have been installed into any target
  operating system - see `docs/distribution/payload.md` (Section 55).
- **First boot not implemented.** No `serein-firstboot.service` or
  equivalent exists anywhere in this repository - that is S7.2.
- **Recovery not implemented.** No recovery partition, restore image,
  rollback partition, or factory reset exists - that is S7.3.
- **Focus runtime not implemented.** Serein Focus remains
  `planning_only` on any media this phase builds - no cgroup write, no
  systemd slice, no boot-time focus auto-selection
  (`docs/focus/architecture.md` is unchanged by S7.0).
- **Secure Boot not verified.** `REAL_SECURE_BOOT=NOT_PERFORMED` in
  every report this phase produces unless an actual Secure-Boot-enabled
  VM/hardware test occurred (Section 31, 97) - "signed upstream boot
  chain files are preserved" is a structural claim this phase can and
  does make (`docs/distribution/iso-build.md`), which is a different,
  weaker claim than "Secure Boot was validated."
- **Physical hardware boot not verified.** `REAL_PHYSICAL_BOOT=NOT_PERFORMED`
  - out of scope without a disposable physical machine (Section 96).

## Real Layer B validation status (S7.0RM7)

**Six real Layer-B runs have now occurred**, each on the exact
reviewed feature HEAD, each exposing a genuine defect this corrective
history has fixed in turn:

```text
Run 1 (after S7.0R):
  RUN_ID=34131219916, RUN_NUMBER=2
  HEAD=fae55499ab992978347a1440f229c1e7d5620ed6
  RESULT=FAILURE - disk-space preflight (~13 GiB free vs. an unjustified
  fixed 20 GiB requirement), before any base ISO was downloaded.
  Evidence-assembly then crashed with FileNotFoundError on a missing
  production manifest. Fixed by S7.0RM (storage reduction + tolerant
  evidence assembly).

Run 2 (after S7.0RM):
  RUN_ID=34139719836
  HEAD=7f09c776704f5c95748cac038b5ac5b4ecfcfb6f
  RESULT=FAILURE - S7.0RM's own storage corrective worked exactly as
  designed:
    FREE_SPACE_BEFORE_CLEANUP_KB=13599048
    FREE_SPACE_AFTER_CLEANUP_KB=38181644
    SPACE_RECLAIMED_KB=24582596
    DISK_PREFLIGHT=PASS
  but the run then failed at
  `./distribution/scripts/fetch-base-image.sh: Permission denied` -
  every direct shell entrypoint under distribution/scripts/ was
  tracked in the Git tree as `100644` (non-executable), so GitHub
  Actions could not invoke any of them directly. Fixed by S7.0RM2
  (Corrective A - `git update-index --chmod=+x` on all six scripts).
  This run also exposed two evidence-fidelity defects (Correctives
  B/C, below) and the disk-preflight arithmetic's own internal
  inconsistency (Corrective D), all fixed in the same pass.

Run 3 (after S7.0RM3):
  RUN_ID=34147196162
  HEAD=37c463f1d8c2642547b6936873e48c67a447abfd
  RESULT=FAILURE - real progress: base download, sha256 verification,
  and signature verification all PASSED against the real
  ubuntu-26.04.1-desktop-amd64.iso, and the S7.0RM3 El Torito evidence
  fix worked (REAL_BASE_EL_TORITO_REPORT=PASS). The run then failed
  during "Build Serein Alpha ISO": the real replayed boot flags
  contained direct base-image byte-range references
  (`--interval:local_fs:...:<base.iso>`), but ephemeral_storage had
  already deleted the base ISO right after report capture, so xorriso
  could not resolve them ("Cannot open local file for interval
  reading"). The real command also showed the base image's own
  `-V "Ubuntu 26.04.1 LTS amd64"` replayed after Serein's own
  `-V SEREIN_ALPHA`, which would have silently won and retitled the
  media. Both fixed by S7.0RM4 (Correctives A and C).

Run 4 (after S7.0RM4):
  RUN_ID=34175627527, RUN_NUMBER=6
  HEAD=5e6c60dccbfca8f6843050e9086b8828e37a14df
  RESULT=FAILURE - the furthest real progress yet: base download,
  sha256 verification, and signature verification all PASSED, the real
  El Torito report PASSED, and - for the first time - the PRODUCTION
  ISO ITSELF FULLY BUILT AND PASSED STRICT INSPECTION:
    production ISO = serein-alpha-26.04-amd64.iso
    sha256 = 6263ec532213958ddd0f0e7d24ffb6e229a2a1e5b4a3e94a03416c4ff6205add
    volume-id = SEREIN_ALPHA, 33 boot flags, media-marker PASS,
    payload-manifest 41 entries hash-verified, STRICT_PASSED.
  The run then failed inside the in-place QA transition:
    PermissionError: [Errno 13] Permission denied:
    build/work/extracted/boot/grub/grub.cfg
  - real Ubuntu ISO extraction preserves file modes such that
  boot/grub/grub.cfg is not necessarily owner-writable, which no
  fixture-based test had exercised. The evidence this run produced was
  ALSO factually wrong: `production_build=fail`, even though production
  had fully succeeded - because the entire "Build Serein Alpha ISO"
  step is one combined shell invocation, so a failure anywhere inside
  it (including after production was already done) looked identical to
  an outright production failure. Both fixed by S7.0RM5 (Correctives A
  and B).

Run 5 (after S7.0RM5):
  RUN_ID=34190149221, RUN_NUMBER=7
  HEAD=55adf8031d65ef5507c3b194d56e24b24cb47b19
  RESULT=FAILURE - RM5 itself proved out: base download/verify/report,
  the production ISO build, AND the in-place QA transition all PASSED
  for the first time (QA transition permissions fix worked). QA ISO
  build also PASSED:
    production ISO = serein-alpha-26.04-amd64.iso
    sha256 = c0adb235bf352fc79efe65ba027a7b663fa30ac167bf3495ce6be7f649dab7c9
    QA ISO = serein-alpha-26.04-amd64-qa.iso
    sha256 = 423c84f8fc0e06c9acedcc54574ec02ba6074de5f13186beef264c945b3982fa
    production_build=pass, qa_transition=pass, qa_build=pass (schema v3)
  The run then failed twice more, independently:
  (1) QA strict inspection crashed with
    PermissionError: [Errno 13] Permission denied:
    dist/inspect-strict-work/iso-strict-extract/serein
  - production and QA strict inspection defaulted to the SAME mutable
  scratch subtree, so the QA inspection's own cleanup of production
  inspection's leftover /serein extraction hit a real permission error.
  (2) QEMU boot smoke then also failed - the real serial log proved the
  boot genuinely reached real systemd/apparmor/snapd userspace
  activity, but no configured positive marker had been observed within
  the fixed 300s TCG timeout, AND the workflow was uploading the WRONG
  serial-log artifact path (build/work/boot-smoke/... instead of the
  real dist/boot-smoke/... the CLI actually wrote to). The evidence
  this run produced was ALSO imprecise: `failure_stage=qemu_boot` even
  though QA strict inspection had failed FIRST - a later, independent
  failure silently overwrote the first real closure blocker. All fixed
  by S7.0RM6 (Correctives A, B, C, D).

Run 6 (after S7.0RM6):
  RUN_ID=34193940964, RUN_NUMBER=8
  HEAD=3466b3ec9fced22d87248db92ab07a14675a5bb8
  RESULT=FAILURE - RM6 itself proved out completely: base
  download/verify/report, production build+inspection, QA
  transition+build+inspection, and real QEMU execution (UEFI,
  `/usr/share/OVMF/OVMF_CODE_4M.fd`, no target disk, no autoinstall)
  ALL PASSED for the first time - every stage up to and including
  formal closure's boot-marker check. The run then failed on the ONE
  remaining check:
    FORMAL_QEMU_BOOT=FAIL, FORMAL_BOOT_MARKER=null
  The real serial log genuinely contained systemd userspace evidence
  equivalent to `[  OK  ] Reached target basic.target - Basic System.`
  - the OS genuinely reached `basic.target` - but the harness's
  literal-substring marker set (`"Reached target Basic System"`, no
  `.target` suffix, no trailing period) never matched real modern
  systemd wording, so a genuine boot success was reported `fail`.
  Fixed by S7.0RM7 (Correctives A and B) - marker recognition fidelity,
  never a lowered standard.
```

The exact-head checkout has now worked correctly in all six real
runs, confirming Corrective A (S7.0R)'s PR-trigger and exact-head model
remain sound across this whole corrective history.

**S7.0RM7 fixes the defect Run 6 exposed:**

- **Corrective A** - `evaluate_boot_log` now strips ANSI CSI/SGR
  terminal control sequences (`_strip_ansi`) before marker evaluation -
  real serial consoles wrap `[  OK  ]`/target names in color codes -
  evaluation-only; the raw captured serial log artifact on disk is
  never modified.
- **Corrective B** - a new, narrowly-scoped regex layer
  (`_TARGET_MARKER_PATTERNS`) recognizes canonical modern systemd
  `Reached target <unit> - <Description>` lines
  (`basic.target`/`multi-user.target`/`graphical.target`), independent
  of and in addition to the legacy literal `DEFAULT_SUCCESS_MARKERS`
  strings (kept for backward compatibility - Section 5). Both layers
  require an explicit reached-target/reached-system EVENT - a queued/
  starting/dependency line naming the same unit, or a
  `"Started <anything>.service"` line, or bare snapd/apparmor/
  cloud-init activity, still never passes. `matched_marker` always
  records the real matched evidence (the exact, whitespace-normalized
  systemd line, or the legacy literal string) - never a bare unit name
  alone. Timeout policy is unchanged (`TCG=600s`, `KVM=300s`) - Run 6
  already reached `basic.target` within the existing bound, so the
  timeout was never the defect.

**S7.0RM6 fixed the defects Run 5 exposed:**

- **Corrective A** - production and QA strict inspection now use
  distinct, uniquely-owned scratch work directories (the CLI's default
  is scoped by the ISO's own filename stem, and the workflow also
  passes explicit `--work-dir dist/inspect-strict-work/production` /
  `.../qa`), so neither invocation ever needs to delete the other's
  leftover extraction. Independently, `inspect_iso_file_strict` is now
  self-cleaning for a stale/read-only scratch tree from a repeated
  invocation: it repairs permissions ONLY inside its own already
  path-confined `iso-strict-extract` subtree (never elsewhere, never
  the source ISO, never `build/work/extracted`, never `sudo`) before
  deleting it, and never chmod's or traverses a symlink found inside it
  (only ever unlinks the link entry itself).
- **Corrective B** - the QEMU boot-smoke step now passes an explicit,
  canonical `--work-dir dist/boot-smoke`, matching what the uploaded
  evidence artifact path actually references (`dist/boot-smoke/
  boot-smoke-serial.log`) - the real serial log is no longer silently
  lost from the evidence artifact. `BootSmokeResult` also gains bounded
  diagnostic fields (`timeout_seconds`, `accelerator`, `serial_log_path`,
  `elapsed_seconds`) for closure investigation, never the full log
  itself.
- **Corrective C** - every step that can produce a real Layer-B failure
  now calls the one canonical `distribution/scripts/record-failure.sh`
  helper instead of an ad-hoc `echo ... > dist/.failure_stage` -
  first-failure-wins: a later, independent failure in the same job can
  no longer overwrite the FIRST real closure blocker's evidence.
- **Corrective D** - TCG (software emulation, e.g. a stock
  GitHub-hosted runner with no `/dev/kvm`) now gets a longer, still
  finite default boot-smoke timeout (600s, up from the prior fixed
  300s) than KVM (unchanged at 300s) - `default_timeout_seconds_for_accel`.
  The positive-marker requirement itself is unchanged and unweakened:
  a running process, reaching UEFI/kernel, or an early/ambiguous
  service line (`snapd.apparmor.service`, `Started arbitrary.service`,
  etc.) still never constitutes a PASS - only a genuine target-level
  marker (`DEFAULT_SUCCESS_MARKERS`) does.

**S7.0RM5 fixed the two defects Run 4 exposed:**

- **Corrective A** - `serein.distribution.qa_boot` now inspects a
  target file's real mode before writing it, temporarily sets the
  owner-write bit only on that exact file if it is not already set,
  writes, and restores the exact original mode afterward - even on
  exception (`try`/`finally`). Applied narrowly at the two write sites
  this module has (the discovered GRUB config, and the internal
  `md5sum.txt` checksum catalog if present and if an update is actually
  needed) plus, for consistency, the older copy-based
  `prepare_qa_variant`. Never a recursive/tree-wide `chmod` - every
  other file's mode is provably untouched
  (`TestQaTransitionPermissions`). Every target path is resolved
  through the same path-safety confinement used elsewhere in the
  codebase (`serein.distribution.pathsafety.resolve_within`) before any
  chmod/write is attempted, failing closed as `QA_TRANSITION=BLOCKED`
  (never `sudo`) if a discovered path - e.g. a symlink - would resolve
  outside the extraction root. The protected-file manifest/
  `QaProtectedFileMutationError` invariant is unchanged and fully
  intact.
- **Corrective B** - `run_build()` now writes
  `dist/build-stage-status.json` (schema v3 of the Layer-B evidence
  model adds the matching `qa_transition` field) the instant each real
  stage - `production_build`, then `qa_transition`, then `qa_build` -
  genuinely completes or fails, never early. The evidence-assembly step
  prefers this marker over the single combined step outcome whenever it
  exists, so "production fully succeeded, QA transition then failed"
  now correctly serializes as `production_build=pass,
  qa_transition=fail, qa_build=not_performed` - never a fabricated
  `production_build=fail`. The closure gate now also requires
  `qa_transition=pass`, so a production-only success still never
  satisfies closure.

**S7.0RM4 fixed the two defects Run 3 exposed:**

- **Corrective A** - the base ISO is now released (in
  `ephemeral_storage` mode) only after every xorriso command that could
  still reference it directly has actually run: after the QA rebuild
  completes, or after QA is cleanly blocked before any QA rebuild
  command is even constructed. Never on an exception path. See
  `docs/distribution/iso-build.md`'s "Base ISO lifetime".
- **Corrective B** - the disk-preflight requirement now includes a
  `BASE_ISO_GIB` term (peak: base + extracted tree + production ISO +
  QA ISO = 28 GiB, +4 GiB margin = 32 GiB required), reflecting that
  the base ISO now survives through both rebuild commands.
- **Corrective C** - `serein.distribution.iso.filter_builder_owned_boot_flags`
  removes only `-V`/`-volid` (and their one value each) from replayed
  report flags before combining them with Serein's own `-V SEREIN_ALPHA`,
  preserving every real boot-architecture flag (including base-image
  interval references) untouched and in order. Fails closed on a
  malformed option/value pair.

**S7.0RM2 fixed all four defects Run 2 exposed:**

- **Corrective A** - all six `distribution/scripts/*.sh` are now
  tracked as `100755` in the Git index (`git ls-files -s
  distribution/scripts/` confirms this directly - never a filesystem
  `chmod` alone, which would not survive a fresh GitHub Actions
  checkout).
- **Corrective B** - `production_build`/`qa_build` are now derived
  from the "Build Serein Alpha ISO" step's own real
  `steps.build.outcome` (`success`/`failure`/`skipped`), never from
  "does a manifest file happen to exist" - an early failure before
  that step ever runs now correctly serializes both as
  `"not_performed"`, not `"fail"`.
- **Corrective C** - a new, always-early "Record pinned base metadata"
  step reads `distribution/base-image.json`'s filename/sha256 right
  after checkout, so `base_filename`/`base_sha256_expected` are always
  populated - even before, or without, a real download - while
  `base_sha256_actual`/`base_verified` remain genuinely
  runtime-only facts.
- **Corrective D** - the disk-preflight requirement is now derived
  from named, internally-consistent components
  (`EXTRACTED_TREE_GIB + PRODUCTION_ISO_GIB + QA_ISO_GIB` = peak,
  + `SAFETY_MARGIN_GIB` = required), replacing the previous
  arithmetic mismatch (documented components summing to far more than
  the enforced 12 GiB).

This development environment still has no `xorriso`/`qemu`/
`squashfs-tools` installed (unchanged from every prior pass this
session), so the S7.0RM7 corrective code itself has only been
validated via the fully injectable fake-`Popen` Layer-A test suite
(`tests/test_distribution.py`, 1288+ tests passing, including a direct
verification that the exact real Run #8 serial line - both bare and
ANSI-wrapped - is recognized, that every weak/ambiguous line the
corrective explicitly must keep rejecting still does, and an
end-to-end `run_boot_smoke()` proof) - not against a seventh real
Layer-B run, which has not yet been observed from this environment:

| Field | Status | Why |
|---|---|---|
| `REAL_UBUNTU_26_04_BASE_VERIFICATION` | **PASS** (Run 6) | Confirmed real: base download, sha256 verify, and signature verify all passed on Run 6 against the real `ubuntu-26.04.1-desktop-amd64.iso`. |
| `REAL_BASE_EL_TORITO_REPORT` | **PASS** (Run 6) | The S7.0RM3 fix continues to hold. |
| `REAL_SEREIN_PRODUCTION_ISO_BUILD` | **PASS** (Run 6) | Production ISO built and strict-inspected successfully. |
| `REAL_SEREIN_PRODUCTION_ISO_INSPECTION` | **PASS** (Run 6) | Strict inspection of the real production ISO passed. |
| `REAL_SEREIN_QA_TRANSITION` | **PASS** (Run 6) | The S7.0RM5 permissions fix continues to hold for real. |
| `REAL_SEREIN_QA_BOOT_ISO_BUILD` | **PASS** (Run 6) | QA ISO built successfully. |
| `REAL_SEREIN_QA_ISO_INSPECTION` | **PASS** (Run 6) | The S7.0RM6 scratch-isolation fix worked for real - production and QA strict inspection no longer collided. |
| `REAL_SEREIN_QEMU_BOOT` | **NOT_PERFORMED** (this pass) | Run 6's real QEMU execution succeeded (UEFI, real OVMF, no target disk, no autoinstall) and the real serial log genuinely contained `Reached target basic.target - Basic System.` - but the harness's literal-substring-only marker set never recognized modern systemd's real wording, so formal `qemu_boot`/closure reported `fail`. Fixed by S7.0RM7 Correctives A/B; not yet re-run for real. |
| `REAL_INSTALLER_REACHABILITY` | **NOT_PERFORMED** | Depends on the above. |
| `REAL_UEFI_BOOT` | **NOT_PERFORMED** | Real OVMF (`/usr/share/OVMF/OVMF_CODE_4M.fd`) was observed launching in Run 6, but closure requires a real matched positive marker, not yet achieved. |
| `REAL_BIOS_BOOT` | **NOT_PERFORMED** | Not exercised - UEFI is the required path. |
| `REAL_SECURE_BOOT` | **NOT_PERFORMED** | No Secure-Boot-capable test environment. |
| `REAL_PHYSICAL_BOOT` | **NOT_PERFORMED** | No disposable physical machine. |

**A WSL2 Ubuntu-24.04 environment is present on this machine** with real
network access and ~895 GB free disk - genuinely capable of running the
full Layer B pipeline locally. Not used in this pass for the same
reason as every prior pass this session: installing packages there
requires `sudo`, which requires a password this session does not have
and should not request interactively.

**PR #9 retains the `run-iso-smoke` label.** `iso-smoke.yml` already
supports `pull_request: synchronize` while the label remains attached -
pushing this corrective's commits should automatically trigger a
seventh real Layer-B run on the new exact HEAD, with no separate action
needed. This repository's `gh` CLI remains unavailable in this
environment (consistent with every prior phase this session), so this
pass could not itself observe that new run's outcome.

```text
S7_0RM7_LAYER_B_TRIGGER_READY=true
S7_0RM7_LAYER_B_RUN=NOT_OBSERVED (auto-triggered by push; outcome must be observed externally)
```

Per the corrective's own merge rule: **`S7_0_READY_FOR_MERGE=NO`**
until a Layer-B run against the exact final S7.0RM7 commit turns every `REAL_*` field above
to a genuine PASS - this document states that blocker honestly rather
than fabricating success. The independent reviewer should watch the
automatically-triggered run (or re-apply/re-trigger it if needed) on
the new HEAD. If that run still fails with a boot marker not observed,
capture the new real serial log/evidence JSON and determine whether it
is (a) a marker-matcher defect still remaining, (b) a genuine boot
regression, or (c) unrelated infrastructure - never widen scope or
weaken the marker/timeout requirements without new real evidence
specifically justifying it (Section 16 of the S7.0RM7 corrective).

## Implementation-scope limitations (this alpha pass specifically)

- **Resolved in S7.0RM7**: `evaluate_boot_log` now recognizes canonical
  modern systemd `Reached target <unit> - <Description>` lines (after
  stripping ANSI terminal control sequences that can wrap them in real
  serial output), in addition to the legacy literal marker strings -
  real Run #6 (Layer-B run #8) genuinely reached `basic.target` but the
  prior literal-substring-only marker set never recognized modern
  systemd's real wording. Weak/ambiguous lines (a queued/starting/
  dependency reference to the same unit, a `"Started ...service"` line,
  bare snapd/apparmor/cloud-init activity) remain rejected exactly as
  before - this is a recognition-fidelity fix, never a lowered
  evidence standard. Boot-smoke timeout policy (`TCG=600s`, `KVM=300s`)
  is unchanged.
- **Resolved in S7.0RM6**: production and QA strict ISO inspection no
  longer default to the same mutable scratch subtree - each gets its
  own uniquely-owned work directory, and the inspector is now
  self-cleaning for stale/read-only scratch content from a repeated
  invocation (scoped strictly to its own already path-confined
  extraction subtree; never the source ISO, never
  `build/work/extracted`, never a symlink's external target, never
  `sudo`).
- **Resolved in S7.0RM6**: the QEMU boot-smoke step now uses an
  explicit, canonical `--work-dir` that matches the uploaded evidence
  artifact's serial-log path exactly - the real serial log is no
  longer silently dropped from Layer-B evidence on a timeout.
- **Resolved in S7.0RM6**: every real Layer-B failure site now records
  through one canonical `record-failure.sh` helper with first-failure-
  wins semantics - a later, independent failure in the same job can no
  longer overwrite the evidence for the actual first closure blocker.
- **Resolved in S7.0RM6**: TCG (software emulation) boot-smoke runs get
  a longer, still-finite default timeout (600s vs. KVM's unchanged
  300s) - a real run's serial log proved genuine boot progress was
  simply slower under software emulation, not defective. The positive-
  marker requirement itself remains unweakened.
- **Resolved in S7.0RM5**: writing the discovered GRUB config (and the
  internal `md5sum.txt` checksum catalog, if present) during the
  in-place QA transition no longer assumes the file is owner-writable -
  a real Ubuntu ISO extraction can preserve a non-owner-writable mode
  on it. The fix is narrowly scoped to the exact file being
  intentionally mutated (never a recursive `chmod`), confined by the
  same path-safety primitive used elsewhere in the codebase, and
  restores the file's exact original mode afterward even on exception.
- **Resolved in S7.0RM5**: `production_build`/`qa_transition`/
  `qa_build` are no longer derived solely from the "Build Serein Alpha
  ISO" step's single combined outcome, which conflated "production
  fully succeeded, QA transition then failed" with an outright
  production failure. `run_build()` now writes a small, authoritative
  `dist/build-stage-status.json` marker the instant each stage
  genuinely completes or fails; the evidence-assembly step prefers it
  whenever it exists, and the Layer-B closure gate now also requires
  `qa_transition=pass`.
- **Resolved in S7.0RM4**: the base ISO is no longer released (in
  `ephemeral_storage` mode) before both rebuild commands have actually
  run - a real report's replayed boot flags can reference the base
  image directly by path, so releasing it after only the report was
  captured (the S7.0RM assumption) broke the real production rebuild.
- **Resolved in S7.0RM4**: replayed upstream volume-ID metadata
  (`-V`/`-volid`) is now filtered out of the report flags before the
  rebuild command is assembled, so the final media's volume ID is
  always exactly `SEREIN_ALPHA`, never silently overridden by the base
  image's own product label.
- **Resolved in S7.0RM2**: every direct shell entrypoint under
  `distribution/scripts/` is now tracked as `100755` in the Git index
  (`git ls-files -s distribution/scripts/` - verified directly, and
  regression-tested by `TestGitExecutableModes`). Previously all six
  were `100644`, which is what caused Run 2's real
  `Permission denied` failure - a filesystem `chmod` on a prior local
  checkout can never fix this, since GitHub Actions always
  materializes whatever mode the Git *tree* itself records.
- **Resolved in S7.0RM2**: `production_build`/`qa_build` in Layer-B
  evidence are now derived from the build step's own real
  `steps.build.outcome`, never from "does a manifest file happen to
  exist" - an early failure before the build step ever runs now
  correctly serializes both as `"not_performed"`, distinct from a
  real `"fail"` (a build step that ran and did not succeed) and a real
  `"pass"`.
- **Resolved in S7.0RM2**: `base_filename`/`base_sha256_expected` in
  Layer-B evidence are now always populated from the committed
  `distribution/base-image.json` (recorded immediately after
  checkout), even before or without a real download -
  `base_sha256_actual`/`base_verified` remain genuinely runtime-only
  facts, never fabricated.
- **Resolved in S7.0RM2**: the disk-preflight requirement is now
  derived from named, internally-consistent components rather than a
  disconnected literal - see `docs/distribution/iso-build.md`'s
  "Storage model" for the exact derivation.
- **The UEFI-evidence heuristic in the strict inspector has not been
  validated against real Ubuntu 26.04.1 `xorriso` output.**
  `_UEFI_EVIDENCE_MARKERS` in `inspect.py` (`appended_part_as_gpt`,
  `--interval:appended_partition`) is a best-effort heuristic derived
  from the generally-documented modern Ubuntu hybrid-ISO layout, not
  copied from a real report this environment could produce (no
  `xorriso` installed here). The first real Layer-B run should save
  the actual `-report_el_torito` output (the workflow already does
  this, to `dist/el-torito-base-report.txt`) and confirm or correct
  this marker list.
- **Resolved in S7.0RM**: the QEMU boot-smoke harness now terminates
  immediately once a positive marker is observed (Corrective D), rather
  than running for its full bounded timeout regardless - see
  `docs/distribution/boot-validation.md`.
- **Resolved/confirmed in S7.0RM2**: the ephemeral-runner-cleanup
  allowlist *has* now been validated against a real `ubuntu-latest`
  run - Run 2 observed
  `FREE_SPACE_BEFORE_CLEANUP_KB=13599048`,
  `FREE_SPACE_AFTER_CLEANUP_KB=38181644`,
  `SPACE_RECLAIMED_KB=24582596` (~23.4 GiB reclaimed), and
  `DISK_PREFLIGHT=PASS` immediately after. The allowlist paths
  (`/usr/local/lib/android`, `/usr/share/dotnet`, `/opt/ghc`,
  `/usr/local/.ghcup`, `/usr/share/swift`) are real and large on the
  actual runner image this workflow uses.
- **`SOURCE_DATE_EPOCH` is not yet threaded through the actual `xorriso`
  invocation.** `BuildManifest.source_date_epoch` exists as a schema
  field and hook (Section 18), but `run_build` does not currently
  compute it from the git commit timestamp or pass it to xorriso -
  byte-level timestamp normalization remains future work.
- **Byte-for-byte reproducibility is not claimed or measured.** Only
  logical reproducibility (Section 17) is claimed - see
  `docs/distribution/iso-build.md`.
- **Only the Desktop edition was researched/pinned.** The Server live
  ISO's checksum was also verified during research (see
  `docs/distribution/base-image.md`) but is not the pinned default;
  switching editions would require updating `distribution/base-image.json`
  deliberately, never silently (Section 5).
- **Signature verification is scripted but not exercised end-to-end
  against the real ISO file** in this pass - `verify-base-image.sh`'s
  GPG step was designed and its key-fetch/verify logic was proven
  against the real `SHA256SUMS`/`SHA256SUMS.gpg` files (see
  `docs/distribution/security.md`), but has not yet been run as part of
  a full `fetch -> verify -> build` sequence against the actual ISO.
- **`distribution/build-config.json`'s `required_tools` reflects only
  the current extraction/overlay/rebuild pipeline** (`xorriso`,
  `python3`, `curl`, `jq`) - it does not include `squashfs-tools`/
  `mtools`/`dosfstools` because the current pipeline does not touch the
  SquashFS live filesystem or EFI/FAT partition contents at all
  (Sections 34-36). A future pass that needs to modify either would
  need to add those tools deliberately, with the explicit staged
  extract/verify/modify/repack process Section 35 requires.
