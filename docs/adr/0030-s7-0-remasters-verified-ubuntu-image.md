# ADR-0030: S7.0 Remasters a Verified Ubuntu Release Image Rather Than Rebuilding Ubuntu From Scratch

## Status

Accepted

## Context

Two materially different strategies could prove Serein can become
bootable media: (a) reproduce Canonical's own build-farm infrastructure
(`livecd-rootfs`, `debootstrap`, package-by-package rootfs assembly)
end to end, or (b) download an official, checksum-verified Ubuntu
release ISO and apply a controlled overlay/remaster on top of it.
`livecd-rootfs` is confirmed real and actively maintained
(`docs/distribution/upstream-installer-research.md` - version `26.04.35`
for the "resolute" series, uploaded 2026-07-22 by the Ubuntu CD Image
Team), but adopting it would mean S7.0's actual goal - proving the
source-repository-to-bootable-media boundary can be crossed at all -
gets buried under the much larger, separate problem of reproducing
Ubuntu's own image-build infrastructure.

## Decision

S7.0 remasters a verified official Ubuntu 26.04.1 Desktop amd64 release
ISO:

```
verified official upstream release ISO + controlled ISO remaster/overlay
```

The base image is pinned by exact filename/sha256/signing-key
fingerprint (`distribution/base-image.json`), never downloaded and
built-against without a fail-closed checksum check
(`serein.distribution.base.verify_base_image`), and never modified in
place - a build only ever writes into `build/work/extracted/` (a copy)
and `dist/` (`docs/distribution/architecture.md`).

The remaster itself only ever writes into an allowlisted overlay
destination (`.disk/`, `serein/`) at the top of the ISO9660 tree - it
never opens, modifies, or repacks the live SquashFS filesystem or the
FAT/EFI partition, so the base image's kernel, initramfs, and signed
boot chain are carried through unmodified
(`docs/distribution/iso-build.md`).

Per Section 6/7's "Integrate → Measure → Replace" guidance, whether
Serein should eventually adopt `livecd-rootfs`-style build
infrastructure is deferred to S8, contingent on measured maintenance
cost of the remaster approach.

## Consequences

- S7.0's dependency list stays small - `xorriso`, `python3`, `curl`,
  `jq` - because the remaster never needs `squashfs-tools`/`mtools`/
  `dosfstools` (`docs/distribution/known-limitations.md`).
- Ubuntu's own release testing, signed boot chain, and hardware
  compatibility work is inherited wholesale rather than re-earned from
  scratch - the same "integrate mature upstream components first"
  principle every S0-S6.5 phase already follows
  (`docs/roadmap.md`'s architecture invariant).
- A future S8 pass that wants byte-level control over the live
  filesystem (e.g. to slim the ISO, or pre-seed a package into the live
  session) has a clean, explicitly-scoped place to add the staged
  SquashFS extract/verify/modify/repack process this ADR's remaster
  approach deliberately does not need yet.

## Alternatives considered

**Reproduce `livecd-rootfs`/full Canonical build-farm infrastructure
immediately.** Rejected for this phase - it solves a different, larger
problem than S7.0's actual goal, and would make "does Serein media boot
at all" depend on first correctly reimplementing Ubuntu's own build
tooling.

**Rebuild from a minimal debootstrap rootfs instead of an official
release ISO.** Rejected - loses the checksum/signature-verifiable
provenance chain a released ISO has (`docs/distribution/security.md`),
and reintroduces exactly the "did we get every package/config Ubuntu
Desktop ships right" risk an official image already resolves.
