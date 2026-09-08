# Known Limitations (S7.0; updated by the S7.0R Layer-B closure corrective; most recently S7.0RM5)

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

## Real Layer B validation status (S7.0RM5)

**Four real Layer-B runs have now occurred**, each on the exact
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
```

The exact-head checkout has now worked correctly in all four real
runs, confirming Corrective A (S7.0R)'s PR-trigger and exact-head model
remain sound across this whole corrective history.

**S7.0RM5 fixes the two defects Run 4 exposed:**

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
session), so the S7.0RM5 corrective code itself has only been
validated via the fully injectable fake-`xorriso` Layer-A test suite
(`tests/test_distribution.py`, 1257+ tests passing, including real
filesystem-mode-bit regressions that chmod a fixture file read-only
before exercising the fix, and fake-runner regressions that fail the
production vs. QA rebuild independently) - not against a fifth real
Layer-B run, which has not yet been observed from this environment:

| Field | Status | Why |
|---|---|---|
| `REAL_UBUNTU_26_04_BASE_VERIFICATION` | **PASS** (Run 4) | Confirmed real: base download, sha256 verify, and signature verify all passed on Run 4 against the real `ubuntu-26.04.1-desktop-amd64.iso`. |
| `REAL_BASE_EL_TORITO_REPORT` | **PASS** (Run 4) | The S7.0RM3 fix continues to hold. |
| `REAL_SEREIN_PRODUCTION_ISO_BUILD` | **PASS** (Run 4) | The production ISO fully built for the first time - `serein-alpha-26.04-amd64.iso`, sha256 `6263ec532213958ddd0f0e7d24ffb6e229a2a1e5b4a3e94a03416c4ff6205add`. |
| `REAL_SEREIN_PRODUCTION_ISO_INSPECTION` | **PASS** (Run 4) | Strict inspection of the real production ISO passed: volume-id=SEREIN_ALPHA, 33 boot flags, media-marker PASS, payload-manifest 41 entries hash-verified. |
| `REAL_SEREIN_QA_BOOT_ISO_BUILD` | **NOT_PERFORMED** (this pass) | Run 4 failed the in-place QA transition itself (`PermissionError` on a real read-only `boot/grub/grub.cfg`) before any QA rebuild command was even constructed. Fixed by S7.0RM5 Corrective A; not yet re-run for real. |
| `REAL_SEREIN_QEMU_BOOT` | **NOT_PERFORMED** | No QA ISO has been produced by a real run yet. The marker-aware monitor (Corrective D) is proven with a fully faked `Popen`/clock (`tests/test_distribution.py::TestBootSmoke`), never a real QEMU process. |
| `REAL_INSTALLER_REACHABILITY` | **NOT_PERFORMED** | Depends on the above. |
| `REAL_UEFI_BOOT` | **NOT_PERFORMED** | No OVMF firmware image available locally; `--require-uefi` fail-closed logic is unit-tested, never exercised against real OVMF. |
| `REAL_BIOS_BOOT` | **NOT_PERFORMED** | No QEMU available. |
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
fifth real Layer-B run on the new exact HEAD, with no separate action
needed. This repository's `gh` CLI remains unavailable in this
environment (consistent with every prior phase this session), so this
pass could not itself observe that new run's outcome.

```text
S7_0RM5_LAYER_B_TRIGGER_READY=true
S7_0RM5_LAYER_B_RUN=NOT_OBSERVED (auto-triggered by push; outcome must be observed externally)
```

Per the corrective's own merge rule: **`S7_0_READY_FOR_MERGE=NO`**
until a Layer-B run against the exact final S7.0RM5 commit turns every `REAL_*` field above
to a genuine PASS - this document states that blocker honestly rather
than fabricating success. The independent reviewer should watch the
automatically-triggered run (or re-apply/re-trigger it if needed) on
the new HEAD.

## Implementation-scope limitations (this alpha pass specifically)

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
