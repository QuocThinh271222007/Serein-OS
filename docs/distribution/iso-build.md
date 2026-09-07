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

## Pipeline stages (S7.0R)

```
1. verify base checksum        serein.distribution.base.verify_base_image
                                (fails closed - BuildError, no extraction on mismatch)

2. reset extraction workspace   serein.distribution.workspace.reset_extracted_workspace
   (guaranteed empty every       (S7.0R Corrective D - never builds on top of a stale
   build - Corrective D)          prior extraction; safe-delete-invariant enforced)

3. extract base ISO             xorriso -osirrox on -indev <base.iso> -extract / <dest>
   (rootless, read-only source)  serein.distribution.iso.build_extract_command

4. apply static overlay          serein.distribution.overlay.apply_overlay
   (allowlisted destinations)     (.disk/, serein/ only - Section 69)

5. build + content-verify         serein.distribution.payload.build_wheel
   the Serein wheel (Corrective C)  + inspect_wheel_contents (fails closed if any
                                       expected serein.* module is missing)

6. assemble resource + wheel       serein.distribution.payload.collect_resource_artifacts
   payload, copy into tree           + wheel_artifact -> serein.distribution.build.
                                        _copy_payload_into_tree

7. write dynamic media marker      serein/manifest.json, serein/payload-manifest.json
   + payload manifest                (Section 53-54) - the wheel appears at
                                       serein/payload/packages/<wheel filename>

8. derive real boot flags           xorriso -indev <base.iso> -report_el_torito as_mkisofs
   from the base image's own          -> serein.distribution.iso.parse_el_torito_report
   el-torito report (Section 38)       (never a hardcoded/tutorial flag set)

9. rebuild CANONICAL production      xorriso -as mkisofs -V SEREIN_ALPHA -r -J -joliet-long
   ISO with xorriso                    <derived boot flags> -o <output> <extracted tree>
                                        serein.distribution.iso.build_rebuild_command

10. record production manifest        dist/<iso>.manifest.json, dist/<iso>.sha256
    + sha256                           serein.distribution.manifest

11. prepare QA serial-boot variant     serein.distribution.qa_boot.prepare_qa_variant
    (Corrective B) - copies the         - fails closed (QA_BUILD=BLOCKED) if no known
    already-assembled production        GRUB config candidate exists, WITHOUT failing
    tree, patches only its GRUB          the already-successful production build
    config, reuses the SAME boot
    flags from step 8 to rebuild a
    second ISO (<name>-qa.iso)

12. record QA manifest + sha256        same as step 10, for the QA output
    (skipped if QA_BUILD=BLOCKED)
```

## Canonical production ISO vs. QA boot variant (Corrective B)

One `run_build()` call produces up to two ISOs from the *same*
extracted base + overlay + payload:

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
