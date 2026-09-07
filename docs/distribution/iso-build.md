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

## Pipeline stages

```
1. verify base checksum        serein.distribution.base.verify_base_image
                                (fails closed - BuildError, no extraction on mismatch)

2. extract base ISO             xorriso -osirrox on -indev <base.iso> -extract / <dest>
   (rootless, read-only source)  serein.distribution.iso.build_extract_command

3. apply static overlay          serein.distribution.overlay.apply_overlay
   (allowlisted destinations)     (.disk/, serein/ only - Section 69)

4. assemble + copy payload        serein.distribution.payload.build_payload_manifest
                                    + serein.distribution.build._write_dynamic_media_content

5. write dynamic media marker      serein/manifest.json, serein/payload-manifest.json
   + payload manifest                (Section 53-54)

6. derive real boot flags           xorriso -indev <base.iso> -report_el_torito as_mkisofs
   from the base image's own          -> serein.distribution.iso.parse_el_torito_report
   el-torito report (Section 38)       (never a hardcoded/tutorial flag set)

7. rebuild ISO with xorriso          xorriso -as mkisofs -V SEREIN_ALPHA -r -J -joliet-long
                                        <derived boot flags> -o <output> <extracted tree>
                                        serein.distribution.iso.build_rebuild_command

8. record build manifest + sha256     dist/<iso>.manifest.json, dist/<iso>.sha256
                                        serein.distribution.manifest
```

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
