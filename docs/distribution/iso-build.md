# ISO Build (S7.0 Sections 6, 12-13, 20, 35-38)

## One canonical build entrypoint (Section 13)

```bash
./distribution/scripts/build-iso.sh
```

which is a thin wrapper (Section 77) around:

```bash
python -m serein.distribution build --source-commit "$(git rev-parse HEAD)"
```

which calls `serein.distribution.build.run_build` - the single pipeline
implementation. There is exactly one build path; nothing else in this
repository builds an ISO.

## Pipeline stages (storage-aware ordering - S7.0RM Corrective A)

```
1. verify base checksum        serein.distribution.base.verify_base_image
                                (fails closed - BuildError, no extraction on mismatch)

2. reset extraction workspace   serein.distribution.workspace.reset_extracted_workspace
   (guaranteed empty every       (S7.0R Corrective D - never builds on top of a stale
   build - Corrective D)          prior extraction; safe-delete-invariant enforced)

3. extract base ISO             xorriso -osirrox on -indev <base.iso> -extract / <dest>
   (rootless, read-only source)  serein.distribution.iso.build_extract_command

4. derive real boot flags           xorriso -indev <base.iso> -report_el_torito as_mkisofs
   from the base image's own          -> serein.distribution.iso.parse_el_torito_report
   el-torito report (Section 38)       (never a hardcoded/tutorial flag set) - captured
                                        here, right after extraction

5. apply static overlay          serein.distribution.overlay.apply_overlay
   (allowlisted destinations)     (.disk/, serein/ only - Section 69)

6. build + content-verify         serein.distribution.payload.build_wheel
   the Serein wheel (Corrective C)  + inspect_wheel_contents (fails closed if any
                                       expected serein.* module is missing)

7. assemble resource + wheel       serein.distribution.payload.collect_resource_artifacts
   payload, copy into tree           + wheel_artifact -> serein.distribution.build.
                                        _copy_payload_into_tree

8. write dynamic media marker      serein/manifest.json, serein/payload-manifest.json
   + payload manifest                (Section 53-54) - the wheel appears at
                                       serein/payload/packages/<wheel filename>

9. rebuild CANONICAL production      xorriso -as mkisofs -V SEREIN_ALPHA -r -J -joliet-long
   ISO with xorriso (bytes             <filtered boot flags> -o <output> <extracted tree>
   finalized on disk here)             serein.distribution.iso.build_rebuild_command -
                                        any builder-owned metadata option the report
                                        itself replayed (-V/-volid) is filtered out first
                                        (S7.0RM4 Corrective C), so the real base-image
                                        interval references this command may still
                                        contain (e.g. --interval:local_fs:...:<base.iso>)
                                        are preserved and resolved against the STILL-
                                        PRESENT base ISO (S7.0RM4 Corrective A)

10. record production manifest        dist/<iso>.manifest.json, dist/<iso>.sha256
    + sha256                           serein.distribution.manifest

11. transition the SAME extraction    serein.distribution.qa_boot.transition_to_qa_in_place
    in place into QA boot form          - S7.0RM Corrective A: no second multi-GB tree
    (Corrective B, storage-             copy. Fails closed (QA_BUILD=BLOCKED) if no known
    efficient as of S7.0RM)             GRUB config candidate exists, WITHOUT failing the
                                         already-finalized production build. Every file
                                         outside the GRUB config + checksum catalog is
                                         hash-verified unchanged, or a
                                         QaProtectedFileMutationError aborts the whole
                                         build (never ships unverified QA media). A real
                                         extracted GRUB config is not necessarily
                                         owner-writable - S7.0RM5 Corrective A temporarily
                                         sets the owner-write bit on ONLY that exact file
                                         (never a recursive chmod), writes, and restores
                                         its exact original mode afterward, even on
                                         exception; every target path is confined via
                                         serein.distribution.pathsafety.resolve_within
                                         first, failing closed as QA_TRANSITION=BLOCKED
                                         on an escape (e.g. a symlink), never `sudo`

12. rebuild QA ISO reusing the         same rebuild command (same filtered boot flags) as
    SAME boot flags from step 4          step 9, targeting the now-QA-form extraction
                                          tree -> <name>-qa.iso - the base ISO must still
                                          be present here too, for the same reason as
                                          step 9

13. record QA manifest + sha256        same as step 10, for the QA output
    (skipped if QA_BUILD=BLOCKED)

14. [ephemeral_storage=True only]    serein.distribution.storage.release_base_iso -
    release the cached base ISO        never for a normal developer build. Only safe
    (S7.0RM Corrective A; timing        now: every xorriso command that could still
    corrected by S7.0RM4                reference the base ISO directly (steps 9 and 12)
    Corrective A)                       has actually run, or QA was cleanly blocked
                                         before step 12 was ever reached. Never released
                                         on an exception path - a genuine failure keeps
                                         the base ISO on disk for forensic inspection.
```

## Build-stage evidence marker (S7.0RM5 Corrective B)

The entire `run_build()` call (steps 1-14 above) is invoked from ONE
combined `./distribution/scripts/build-iso.sh` shell step in
`.github/workflows/iso-smoke.yml` - a real Layer-B run proved that
step's own overall outcome (success/failure) is too coarse to evaluate
alone: production can fully succeed (steps 1-10) and the run can still
fail afterward, purely in the QA transition (step 11) or QA rebuild
(step 12).

`run_build()` writes `dist/build-stage-status.json`
(`serein.distribution.build.stage_status_path` /
`BuildStageStatus` / `load_build_stage_status`) the instant - and only
the instant - each of `production_build`, `qa_transition`, `qa_build`
genuinely completes or genuinely fails, e.g.:

```json
{
  "production_build": "pass",
  "qa_transition": "fail",
  "qa_build": "not_performed",
  "failure_stage": "qa_transition",
  "failure_reason": "QA transition safety check failed: ..."
}
```

`python -m serein.distribution evidence --build-stage-status
dist/build-stage-status.json` reads this marker when present and lets
it override the coarser `--production-build`/`--qa-transition`/
`--qa-build` flags (and `--failure-stage`/`--failure-reason`, if the
marker recorded a failure) that `iso-smoke.yml` still passes as a
fallback for the case where `run_build()` never got far enough to write
it at all (e.g. an even earlier failure, before any stage began). This
is deliberately the one stage-progress marker mechanism - never several
competing ones - and its corresponding Layer-B evidence field is
`qa_transition` (schema v3 of
`schemas/distribution-layer-b-evidence.schema.json`); the closure gate
(`serein.distribution.closure.enforce_layer_b_closure`) now also
requires `qa_transition == "pass"`, so a production-only success can
never by itself satisfy closure.

## Canonical production ISO vs. QA boot variant (Corrective B)

One `run_build()` call produces up to two ISOs from the *same*
extraction directory (never a second multi-GB copy as of S7.0RM
Corrective A) - the production ISO's bytes are always finalized on
disk *before* the QA transition is even allowed to begin:

```
serein-alpha-26.04-amd64.iso       canonical production media - normal
                                     graphical live-boot default, unmodified
                                     from the base image's own GRUB config
                                     except for the allowlisted serein/.disk
                                     overlay - never carries autoinstall,
                                     never auto-selects a QA/serial entry

serein-alpha-26.04-amd64-qa.iso    QA-only variant - identical Serein
                                     payload, identical Ubuntu SquashFS/
                                     kernel/initramfs, identical boot
                                     flags; only its GRUB config differs:
                                     a new QA menu entry (reusing the
                                     production entry's own real
                                     linux/initrd paths, plus
                                     console=ttyS0,115200n8, minus
                                     `quiet`) is prepended and forced to
                                     boot automatically
                                     (`set default="0"` + a short
                                     `set timeout`) - never autoinstall,
                                     never a disk target
```

The QEMU boot-smoke harness (`docs/distribution/boot-validation.md`)
always boots the **QA** variant, never the canonical production ISO -
booting the QA variant proves the shared kernel/initramfs/live-userspace
genuinely works; it does not by itself validate the canonical entry's
own default-boot behavior, and this documentation never conflates the
two (Section 20).

## Wheel embedding (Corrective C)

`serein.distribution.payload.build_wheel` runs
`python -m build --wheel --no-isolation` (fast, network-free - this
interpreter's own already-installed `setuptools`/`wheel`, never an
isolated build environment that would need a PyPI fetch) as part of
every canonical build. `inspect_wheel_contents` then opens the wheel's
own zip index and fails closed
(`serein.distribution.payload.WheelContentError`) if any of
`EXPECTED_WHEEL_MODULES` (representative paths across the CLI core and
every completed phase - `serein/cli.py`, `serein/ai/__init__.py`,
`serein/cyber/__init__.py`, `serein/veil/__init__.py`,
`serein/focus/__init__.py`, `serein/distribution/__init__.py`) is
missing. The wheel is embedded at
`serein/payload/packages/<wheel filename>` and covered by the same
payload-integrity hashing as every other entry - never installed
anywhere, only embedded (Section 55/26).

## Volume-ID replay filtering (S7.0RM4 Corrective C)

`build_rebuild_command` places `-V SEREIN_ALPHA` at the front of the
rebuild argv, followed by the boot flags derived from the base image's
own real `-report_el_torito as_mkisofs` output. A real Layer-B run
exposed a real Ubuntu report also carrying the upstream product's own
volume metadata - `-V "Ubuntu 26.04.1 LTS amd64"` (or the `-volid`
alias) - and since xorriso resolves multiple `-V` options on one
command line by taking the *last* one, replaying that token after
Serein's own would have silently retitled the final media.

`serein.distribution.iso.filter_builder_owned_boot_flags` removes only
`-V`/`-volid` and their one value each from the replayed flags,
preserving every other option - including the real base-image interval
references (`--interval:local_fs:...`), `--grub2-mbr`,
`-append_partition`, `-c`, `-b`, and everything else - in their
original order and identity. It is deliberately conservative: any
option it does not recognize as builder-owned is assumed to be real
boot-architecture data and is never touched, and it fails closed
(`IsoCommandError`) if an owned option appears with no following value
rather than silently producing a corrupted argv. `build_rebuild_command`
applies this filter automatically before combining the result with
`-V <volume_id>`, so the final rebuild argv always carries exactly one
effective volume-ID contract.

## Clean build workspace (Corrective D)

`serein.distribution.workspace.reset_extracted_workspace` runs before
every extraction. It requires the target to resolve to exactly
`<work_dir>/extracted` (the one canonical extraction path) *and* pass
`pathsafety.is_safe_cleanup_target` before deleting anything - a
symlinked or out-of-scope `extracted/` is rejected, never silently
followed. `cache/upstream/` (the verified base) and `dist/` (prior
build output) are never referenced by this function at all, so a
workspace reset can never touch either.

## Storage model (S7.0RM Corrective A)

A real Layer-B run on a stock `ubuntu-latest` GitHub-hosted runner
measured ~13 GiB free against the S7.0R workflow's fixed 20 GiB
preflight requirement, and failed before any base ISO was even
downloaded. Rather than lowering the threshold (which would have
hidden the real peak-storage problem), the pipeline itself was made
storage-efficient:

- **No second extraction tree for QA.** The prior design
  (`prepare_qa_variant`, still available as a lower-level, independently
  tested utility) `copytree`'d the entire multi-GB extraction for the
  QA variant. `run_build` now uses
  `qa_boot.transition_to_qa_in_place` instead - the production ISO is
  built and finalized first, then the *same* extraction directory is
  patched in place for the QA rebuild. See "Canonical production ISO
  vs. QA boot variant" above for the safety net that makes this sound
  (every non-GRUB-config file is hash-verified unchanged).
- **The cached base ISO is released only after its last real consumer,
  in ephemeral CI mode.** An earlier version of this pipeline released
  it immediately after extraction and the El Torito report were
  captured, on the assumption that neither rebuild command would ever
  need it again. A real Layer-B run proved that assumption false: a
  real report's own boot/system-area flags can reference the base
  image directly by path for a boot-critical byte range (e.g.
  `--interval:local_fs:...:<base.iso>`), and both rebuild commands
  replay those flags. `run_build(..., ephemeral_storage=True)` now
  deletes `cache/upstream/<base>.iso` only after the QA rebuild has
  actually completed (or QA was cleanly blocked before any QA rebuild
  command was ever constructed) - see "Base ISO lifetime" below. This
  is opt-in and explicit (`--ephemeral-storage` / `EPHEMERAL_STORAGE=1`);
  a normal developer build never deletes its verified cache, and a
  genuine build/QA failure never triggers deletion either - the base
  ISO stays available for forensic inspection.
- **Ephemeral GitHub-hosted-runner SDK cleanup.** `iso-smoke.yml`
  additionally reclaims a small, exact allowlist of large preinstalled
  SDK trees (Android, .NET, GHC, Swift) it never uses, scoped to
  `runner.environment == 'github-hosted'` only - never a self-hosted
  runner or a developer machine, and never a glob deletion. See
  `docs/distribution/security.md`.
- **Diagnostics, not estimates, drive the preflight.** `df`/`du`
  output is logged at each transition point in the workflow
  (`serein.distribution.storage.measure_disk_usage` is the equivalent
  Python-side helper, used by tests).

### Base ISO lifetime (S7.0RM4 Corrective A)

The correct invariant is:

```
all xorriso commands containing base-image interval references completed
=> base image may be released in ephemeral mode
```

never the earlier (disproven) claim "El Torito report captured => base
image no longer needed". Concretely, `run_build` only calls
`storage.release_base_iso` at three points, all after every possible
consumer has run:

- right before returning when `build_qa_variant=False` (production
  rebuild was the only consumer),
- right after `qa_boot.transition_to_qa_in_place` raises `QaBootError`
  (QA was cleanly blocked - no QA rebuild command was ever
  constructed, so nothing further will reference the base ISO),
- right after the QA rebuild command has actually run and the QA
  manifest is written.

It is never called from an exception path (a `QaProtectedFileMutationError`
or any rebuild-command failure propagates as `BuildError` with the base
ISO left untouched) - correctness and forensic evidence outrank
maximizing disk reclamation (Section 5 of the S7.0RM4 corrective).

### Disk-preflight requirement derivation (S7.0RM2 Corrective D, revised by S7.0RM4 Corrective B)

An earlier version of this threshold (12 GiB) was not actually derived
from its own documented components - they summed to significantly
more than the number enforced. A later revision (22 GiB) was internally
coherent but omitted the base ISO entirely, based on the
now-corrected assumption above. The current requirement is computed in
the workflow from named, internally-consistent components reflecting
the *real* simultaneously-live large-object peak - now including the
base ISO, which survives through both rebuild commands:

```
BASE_ISO_GIB (7)           the real pinned Desktop ISO is ~6.0 GB
                            (docs/distribution/base-image.md), rounded
                            up for filesystem overhead - now retained
                            through both rebuild commands (Corrective A)
+ EXTRACTED_TREE_GIB (7)    xorriso -osirrox extracts the ISO9660 tree's
                            files exactly as stored - the live SquashFS
                            payload is copied out as one still-
                            compressed blob, never re-expanded, so the
                            extracted tree's apparent size stays close
                            to the base ISO's own size
+ PRODUCTION_ISO_GIB (7)    deliberately RETAINED on disk while the QA
                            ISO is rebuilt (the production ISO must
                            already be finalized and unaffected before
                            the QA transition begins)
+ QA_ISO_GIB (7)            being written by the second xorriso rebuild
= PEAK_GIB (28)              all four exist simultaneously during the
                              QA rebuild step - the true peak
+ SAFETY_MARGIN_GIB (4)      rough size estimates, not measured
= REQUIRED_GIB (32)
```

`tests/test_distribution.py::TestLayerBWorkflow`'s Corrective D/B tests
regress that these components' own literal values actually sum to the
enforced requirement, not merely document an unrelated number.

## Why extraction/rebuild instead of SquashFS/EFI-partition surgery (Sections 34-36)

S7.0's overlay only ever writes into `.disk/`/`serein/` at the top of
the ISO9660 tree - it never opens, modifies, or repacks the live
SquashFS filesystem, and never touches the FAT/EFI partition's
contents. This means:

- No `squashfs-tools`/`mtools`/`dosfstools` dependency (Section 19 -
  "only require tools actually used"; `distribution/build-config.json`'s
  `required_tools` reflects this).
- The base image's own compression parameters, initramfs, kernel, and
  signed boot chain (shim/GRUB/kernel/initramfs signatures) are carried
  through completely unmodified (Sections 33-36, 32) - there is no
  repack step that could silently change them.
- Boot flags are re-derived from the *actual* base image's own
  `-report_el_torito` output every build (Section 38), so xorriso's
  rebuild reproduces the same El Torito/GPT/boot-catalog structure the
  original media had, rather than a guessed or copied-from-a-tutorial
  flag set (Section 39).

If a future phase needs to modify the live filesystem itself (e.g. to
pre-seed a package into the live session), that is a materially bigger
change - explicit SquashFS extract/verify/modify/repack stages
(Section 35), with compression parameters preserved deliberately
(Section 36) - and is out of scope for this alpha pass; see
`docs/distribution/known-limitations.md`.

## Rootless (Section 20)

Nothing in the pipeline requires `sudo` or a mount. `xorriso -osirrox on`
extracts an ISO9660 tree without mounting it; the rebuild step
(`xorriso -as mkisofs`) reads a plain directory tree. No step in
`build.py` invokes `mount`, `losetup`, or any privileged operation.

## Reproducibility contract (Section 17-18)

**Logical reproducibility** (same base + same Serein commit + same
build tool versions + same overlay -> same logical content) is the
guarantee this phase makes:

- The base image is pinned and checksum-verified (Section 9-10).
- The payload manifest is deterministic for a given `source_commit`
  (`docs/distribution/payload.md`).
- `BUILDER_VERSION`/`OVERLAY_VERSION`
  (`serein.distribution.models`) are recorded in every build manifest,
  so a content difference between two builds against the same commit
  is always attributable to a tooling/overlay version change, never
  silent drift.

**Byte-for-byte reproducibility** is *not* claimed in this pass -
ISO9660/xorriso timestamps and the base image's own embedded metadata
can vary run-to-run even with identical logical inputs. `SOURCE_DATE_EPOCH`
support exists in the build manifest schema
(`source_date_epoch`, sourced from the git commit's own timestamp when
set) as a documented hook for a future pass to wire through to xorriso's
own timestamp-normalization options - it is not yet threaded through the
actual `xorriso -as mkisofs` invocation in this alpha pass (see
`docs/distribution/known-limitations.md`). Do not read `verified`
anywhere in this codebase as a byte-reproducibility claim; it is not
one.

## Filename convention (Section 15)

```
serein-alpha-<release>-<architecture>.iso
```

e.g. `serein-alpha-26.04-amd64.iso` - deterministic, no timestamp in the
canonical filename. (`distribution/build-config.json`'s
`iso_filename_template` records this exactly.)
