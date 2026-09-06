# Known Limitations (S1)

Explicit per the S1 requirement not to overstate what has been validated.

## Resolved by S1R (live validation pass)

The items below were originally listed here as untested and have since
been verified against a real Ubuntu 26.04 + Plasma 6.6 environment (a
disposable, isolated WSL2 instance — see `docs/validation/s1r/`):

- Package existence and dependency closure for the full 17-package set
  (`docs/validation/s1r/package-validation.md`) — one real defect was
  found and fixed (`breeze-gtk` → `breeze-gtk-theme`).
- `/etc/xdg/kdeglobals`/`/etc/xdg/kwinrc` ownership (confirmed unowned by
  any package, before and after a real full install) and KConfig
  cascading precedence, empirically (`docs/validation/s1r/
  config-ownership-validation.md`).
- The `org.serein.desktop` Look-and-Feel KPackage's `metadata.json`,
  installed and inspected with the real `kpackagetool6` — accepted with
  no errors — and its panel layout script, proven to actually execute and
  produce the intended bottom-panel widget order on a real, running
  `plasmashell` (`docs/validation/s1r/plasma-runtime-validation.md`).
- The SDDM `.conf.d` drop-in mechanism and its precedence, confirmed
  against the real `sddm` package's own man page and Kubuntu's own
  shipped drop-ins (`docs/validation/s1r/sddm-validation.md`).

**Still not live-tested** (see `docs/validation/s1r/known-blockers.md` for
why, in detail): SDDM's actual interactive login/authentication flow (no
VT/DRM device in WSL2), real-display HiDPI scaling, and multi-monitor
behavior. None of these are known defects — they are gaps in what this
validation environment could exercise, not evidence something is broken.

A live-VM (or Kubuntu 26.04 test image) validation pass with a real or
virtual GPU display remains the recommended next step for those three
specific items before any of this ships to a real installer (S7).

## Package dependency closure

Resolved by S1R — see above and `docs/validation/s1r/
package-validation.md` for exact versions and the simulated/real
transaction results.

## Config-marker granularity

The Serein-managed marker (`/etc/serein/desktop/config-version`) is
host-wide, not per-user. It cannot express "Serein Desktop is
partially configured" or "applied for some users but not others." This
is an acceptable S1 simplification since no Apply step exists yet to
create that ambiguity in practice; it should be revisited if/when a real
Apply implementation shows it matters.

## KDE Activities

Per the explicit S1 scope limit, KDE Activities were not evaluated beyond
this note: virtual desktops (not Activities) are Serein's default
workspace model in S1. Activities remain a documented option for a later
phase if a concrete need emerges — no invariant here depends on them.

## `serein desktop status`/`doctor` on this development host

This repository was developed and validated on a Windows machine with no
KDE Plasma installed. `desktop doctor`'s Plasma/KWin/SDDM checks
correctly report `SKIP` there ("not installed, not Serein-managed yet") —
this is the intended, honest behavior for an unconfigured host, not a
workaround. See the S1 completion report for the exact recorded output.
