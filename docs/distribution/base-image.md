# Base Image Selection (S7.0 Section 5, 9-11)

## Selected image

```
distribution: ubuntu
release:      26.04 (point release 26.04.1)
codename:     resolute
architecture: amd64
edition:      desktop
filename:     ubuntu-26.04.1-desktop-amd64.iso
```

Pinned in `distribution/base-image.json`, validated against
`schemas/distribution-base-image.schema.json`.

## Why Desktop, not Server (Section 5)

Both the Desktop and Server images use the same Subiquity installer
backend (see `docs/distribution/upstream-installer-research.md`) - the
choice is not about installer architecture. It is about which live
environment is the least-complex base for a *desktop-oriented* Serein
image (Serein installs a KDE Plasma desktop per S1):

- The Desktop ISO already boots into a working live GUI session -
  useful infrastructure-proof value for S7.0's mission ("prove Serein
  crosses the source -> bootable-media boundary") without S7.0 having
  to build or fork any UI itself (Section 3).
- The Server image's live-install environment has no graphical session
  at all, which is a materially worse fit for a workstation-focused
  project even at the prototype stage, and would need extra
  justification to choose over Desktop per Section 5 ("If rigorous
  investigation shows the Server live ISO is materially more
  appropriate ... document the reasoning before choosing it"). No such
  case was found.
- Serein's own KDE Plasma configuration is **not** applied by S7.0 -
  that remains S7.1/S7.2 provisioning work. The Desktop ISO's live
  GNOME session is upstream, unmodified media content in this phase.

## Why the 26.04.1 point release, not the original 26.04 GA files

`releases.ubuntu.com/26.04/` publishes both `-26.04-` (original GA) and
`-26.04.1-` (current point release, checksums dated 2026-08-27) desktop
images. 26.04.1 is the release Canonical currently directs new
installs toward; it is still the same `26.04` LTS series (`point_release`
in the contract), not a different release. Both checksums were verified
during this research (see `docs/distribution/security.md`) - either
could be pinned; 26.04.1 was chosen as the more current, still-supported
option.

## Checksum provenance (Section 9-10)

`distribution/base-image.json`'s `sha256` field was read directly from
`https://releases.ubuntu.com/26.04/SHA256SUMS`, fetched via `curl`
(never summarized through an intermediate tool that could transcribe a
hex digest incorrectly) on 2026-09-07:

```
601e30fbf5d97759367c632e2c33630665039b7e2158fd068403da3ccf1bda1f *ubuntu-26.04.1-desktop-amd64.iso
```

That checksum file's own authenticity was verified against
`SHA256SUMS.gpg` and the Ubuntu CD Image Automatic Signing Key (2012),
fingerprint `843938DF228D22F7B3742BC0D94AA3F0EFE21092`, fetched by exact
fingerprint from `keyserver.ubuntu.com` - see
`docs/distribution/security.md` for the full command sequence and
result. This proves the *pinned checksum value* is authentic; it is a
separate, still-outstanding step to download the actual 6.0 GB ISO and
verify its bytes hash to this value - `verified: false` in
`base-image.json` records that honestly (see
`docs/distribution/known-limitations.md`).

## `edition`/`architecture` are structurally constrained

`schemas/distribution-base-image.schema.json` only accepts
`architecture: "amd64"` and `edition: "desktop"|"server"` -
`serein.distribution.base.load_base_image_spec` additionally rejects
any other `distribution` value at load time (fail closed on a malformed
or tampered contract file), independent of the JSON Schema check.
