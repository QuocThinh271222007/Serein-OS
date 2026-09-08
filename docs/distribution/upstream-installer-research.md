# Upstream Ubuntu 26.04 Installer Research (S7.0 Section 4)

**Date checked:** 2026-09-07, during this S7.0 implementation pass.

This document records what was independently verified about current
Ubuntu 26.04 release/installer architecture *before* any S7.0 code was
written, per Section 4's explicit requirement not to assume deprecated
(Ubiquity-era) installer behavior.

## Release status

`https://releases.ubuntu.com/26.04/` (fetched 2026-09-07) lists Ubuntu
**26.04.1 LTS ("Resolute Raccoon")** as the current point release, with
`ubuntu-26.04.1-desktop-amd64.iso` (6.0 GB) and
`ubuntu-26.04.1-live-server-amd64.iso` (2.7 GB) both published, alongside
the original `-26.04-` filenames. `SHA256SUMS`/`SHA256SUMS.gpg` on that
page are dated 2026-08-27. The original 26.04 GA files remain published
alongside the 26.04.1 point-release refresh - both were checksummed
during this research (see `distribution/base-image.json`).

## Installer backend: Subiquity, not Ubiquity

Per Canonical's own Subiquity documentation
(`canonical-subiquity.readthedocs-hosted.com`, fetched 2026-09-07):

> "Ubuntu Server (20.04+) and Desktop (23.04+) both support autoinstall
> functionality."

This confirms the architecture Section 4 expected:

```
Ubuntu 26.04 LTS
Ubuntu Desktop Installer/Bootstrap UI
        v
Subiquity backend (shared with Server, since Desktop 23.04+)
        v
curtin (partitioning/filesystem application)
```

The old Ubiquity (GTK, `ubiquity` package) installer is **not** the
current architecture and was correctly *not* assumed. Both Server and
Desktop images have used Subiquity as their installer backend since
their respective introduction releases noted above, well before 26.04.

## Autoinstall

Autoinstall ("unattended"/"hands-off"/"preseeded" installation, per
Subiquity's own docs) is a real, currently-supported mechanism. The
provided-autoinstall reference documents `subiquity.autoinstallpath=`
as a kernel command-line parameter used to point the installer at an
autoinstall config file (in addition to placing `autoinstall.yaml` at
the root of the install medium, which Subiquity auto-detects).
Subiquity's intro page states plainly that "if there is any autoinstall
configuration at all, the autoinstall takes the default for any
unanswered question" - i.e. presence of *any* autoinstall config changes
installer behavior for every unanswered question, which is exactly why
Section 40's prohibition on shipping this as a production default
matters. This is also why S7.0's own regression
(`tests/test_distribution.py::TestAutoinstallSafety`) statically checks
that the production boot configuration never carries `autoinstall` on
a non-QA-labeled entry - see `docs/distribution/security.md`.

Live verification of Subiquity's own confirmation-prompt safeguard
mechanics (e.g. `interactive-sections`) was not reachable from the
specific documentation pages fetched in this pass; S7.0 does not rely
on that safeguard existing anyway - the QA-only serial boot entry
(`distribution/boot/qa-serial-entry.cfg`) never sets `autoinstall` at
all, and the production boot path never carries it either. Automated
boot-smoke validation (Section 45-49) only ever proves the live
environment *boots*, never that installation proceeds.

## livecd-rootfs

`launchpad.net/livecd-rootfs` (fetched 2026-09-07) describes itself as
"a small build system for the live filesystem included on Ubuntu
desktop CDs," maintained by the Ubuntu CD Image Team, with recent
uploads including version `26.04.35` for "Resolute" (2026-07-22) -
confirming it remains Canonical's actively-maintained build
infrastructure for official Ubuntu images today, consistent with the
codename `resolute` pinned in `distribution/base-image.json`.

Per Section 7 and Section 6's "Integrate → Measure → Replace" guidance,
S7.0 deliberately does **not** adopt livecd-rootfs itself - it remasters
a verified official release ISO instead (Section 6's stated rationale:
"S7.0 goal = first reproducible Serein media, not reimplement Ubuntu
image infrastructure"). Whether Serein should eventually build via
livecd-rootfs-style flavor infrastructure is deferred to S8, contingent
on measured maintenance cost of the remaster approach - see
`docs/distribution/s7-roadmap.md`.

## Conclusion for S7.0's base-image choice

- Ubuntu 26.04 LTS is real, released, and current as of this research.
- Desktop and Server images both use the same (Subiquity) installer
  backend - the choice between them for S7.0 is not about installer
  architecture, it is about which live environment is the least-complex
  base for a desktop-oriented Serein image (Section 5) - see
  `docs/distribution/base-image.md` for that reasoning.
- No deprecated Ubiquity assumption was made anywhere in this
  implementation.
