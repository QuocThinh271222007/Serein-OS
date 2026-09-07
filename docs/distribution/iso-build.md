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
                                        here, right after extraction, because it is the
                                        LAST step that still needs base_iso to exist

5. [ephemeral_storage=True only]    serein.distribution.storage.release_base_iso -
   release the cached base ISO        never for a normal developer build, only an
   (S7.0RM Corrective A) - it is       explicit ephemeral-CI build; frees ~6 GB before
   never needed again after step 4     the two ISO rebuilds (the highest disk-pressure
                                        phase) even begin

6. apply static overlay          serein.distribution.overlay.apply_overlay
   (allowlisted destinations)     (.disk/, serein/ only - Section 69)

7. build + content-verify         serein.distribution.payload.build_wheel
   the Serein wheel (Corrective C)  + inspect_wheel_contents (fails closed if any
                                       expected serein.* module is missing)

8. assemble resource + wheel       serein.distribution.payload.collect_resource_artifacts
   payload, copy into tree           + wheel_artifact -> serein.distribution.build.
                                        _copy_payload_into_tree

9. write dynamic media marker      serein/manifest.json, serein/payload-manifest.json
   + payload manifest                (Section 53-54) - the wheel appears at
                                       serein/payload/packages/<wheel filename>

10. rebuild CANONICAL production     xorriso -as mkisofs -V SEREIN_ALPHA -r -J -joliet-long
    ISO with xorriso (bytes            <derived boot flags> -o <output> <extracted tree>
    finalized on disk here)            serein.distribution.iso.build_rebuild_command

11. record production manifest        dist/<iso>.manifest.json, dist/<iso>.sha256
    + sha256                           serein.distribution.manifest

12. transition the SAME extraction    serein.distribution.qa_boot.transition_to_qa_in_place
    in place into QA boot form          - S7.0RM Corrective A: no second multi-GB tree
    (Corrective B, storage-             copy. Fails closed (QA_BUILD=BLOCKED) if no known
    efficient as of S7.0RM)             GRUB config candidate exists, WITHOUT failing the
                                         already-finalized production build. Every file
                                         outside the GRUB config + checksum catalog is
                                         hash-verified unchanged, or a
                                         QaProtectedFileMutationError aborts the whole
                                         build (never ships unverified QA media)

13. rebuild QA ISO reusing the         same rebuild command as step 10, targeting the
    SAME boot flags from step 4          now-QA-form extraction tree -> <name>-qa.iso

14. record QA manifest + sha256        same as step 11, for the QA output
    (skipped if QA_BUILD=BLOCKED)
```

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
- **The cached base ISO is released early in ephemeral CI mode.**
  `run_build(..., ephemeral_storage=True)` deletes
  `cache/upstream/<base>.iso` immediately after extraction and the El
  Torito report are both captured - the last two things the pipeline
  ever needs it for - freeing ~6 GB before the two ISO rebuilds (the
  highest disk-pressure phase) begin. This is opt-in and explicit
  (`--ephemeral-storage` / `EPHEMERAL_STORAGE=1`); a normal developer
  build never deletes its verified cache.
- **Ephemeral GitHub-hosted-runner SDK cleanup.** `iso-smoke.yml`
  additionally reclaims a small, exact allowlist of large preinstalled
  SDK trees (Android, .NET, GHC, Swift) it never uses, scoped to
  `runner.environment == 'github-hosted'` only - never a self-hosted
  runner or a developer machine, and never a glob deletion. See
  `docs/distribution/security.md`.
- **Diagnostics, not estimates, drive the preflight.** `df`/`du`
  output is logged at each transition point in the workflow
  (`serein.distribution.storage.measure_disk_usage` is the equivalent
  Python-side helper, used by tests). The preflight's 12 GiB threshold
  is a documented, conservative estimate (base ISO until released + one
  extraction tree + up to two rebuilt ISOs existing briefly together +
  a 2 GiB margin) - explicitly not claimed to be byte-exact.

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
