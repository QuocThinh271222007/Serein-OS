# ADR-0031: Production Media Never Defaults to Unattended Autoinstall

## Status

Accepted

## Context

Subiquity (the shared Ubuntu Server/Desktop installer backend since
Desktop 23.04+ - `docs/distribution/upstream-installer-research.md`)
supports a real `autoinstall` mechanism: per Canonical's own docs, "if
there is any autoinstall configuration at all, the autoinstall takes
the default for any unanswered question" - meaning presence of
autoinstall config anywhere on the medium or kernel command line
changes installer behavior globally, not just for one menu entry. That
same mechanism is exactly what a QEMU boot-smoke/installer-reachability
automation harness needs in order to validate the installer
non-interactively. Left unguarded, it is also exactly the mechanism
that could silently turn "try Serein" into "wipe this disk" for a real
user who never asked for that.

## Decision

- The **production** boot path never carries `autoinstall` on its
  kernel command line or via an on-medium `autoinstall.yaml` at the ISO
  root - `serein.distribution.safety.scan_boot_config_for_default_autoinstall`
  regresses this against the actual boot configuration a build would
  ship.
- Automation-only `autoinstall` usage is confined to a **structurally
  separate**, distinctly-titled QA/automation boot entry
  (`distribution/boot/qa-serial-entry.cfg` for boot-smoke does not even
  need `autoinstall` - it only adds `console=ttyS0` for serial-log
  capture) - if a future pass needs a real autoinstall-driven VM
  validation entry, it must carry a title the scanner's `_QA_ENTRY_MARKERS`
  recognizes (`qa`, `automation`, `boot-smoke`, `test`), never reuse the
  production entry's title.
- No default disk target (`/dev/sda`, `/dev/nvme0n1`, or equivalent) is
  ever hardcoded anywhere in this repository (Section 43) - S7.0
  performs zero disk mutation of any kind, so this has no code path to
  even exist yet, but the invariant is recorded here so S7.1 (the first
  phase that can touch a real disk) inherits it as a hard constraint,
  not a suggestion.
- QEMU boot-smoke validation never attaches a writable target disk
  (Sections 44, 92) - `build_qemu_boot_command` never emits `-hda`/
  `-drive` for anything but a read-only OVMF firmware image.

## Consequences

- A user who boots Serein Alpha media to "just look at it" can never be
  surprised by an unattended install - the interactive installer
  safeguard Subiquity already provides is never bypassed by anything
  Serein adds.
- CI/QA automation still has a real, working path to validate the
  installer reaches a usable state (Section 93,
  `REAL_INSTALLER_REACHABILITY`) without that path being reachable from
  a normal boot.
- The regression in `tests/test_distribution.py::TestAutoinstallSafety`
  fails loudly (not silently) if a future change accidentally moves
  `autoinstall` onto the default entry - this is treated as a
  high-severity blocker (Section 113), not a warning.

## Alternatives considered

**Rely on Subiquity's own interactive confirmation prompt as the only
safeguard.** Rejected as insufficient on its own - that prompt's exact
behavior/disableability was not independently re-verified from the
documentation reachable during this pass's research
(`docs/distribution/upstream-installer-research.md`), so Serein's own
static regression is a safeguard that does not depend on trusting an
upstream behavior this project has not independently confirmed.
