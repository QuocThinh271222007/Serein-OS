# Known Limitations (S1)

Explicit per the S1 requirement not to overstate what has been validated.

## Not live-tested

Nothing in this phase has been applied to, or observed running on, a real
Ubuntu 26.04 + KDE Plasma 6.6 machine. Specifically not verified against a
live system:

- That the exact package list in `desktop/packages.py` installs cleanly
  and pulls in every transitive dependency needed for a working session
  (no live `apt-cache`/`apt install --dry-run` access from this
  development environment — see `package-strategy.md`).
- That the `/etc/xdg/kdeglobals`/`/etc/xdg/kwinrc` fragments produce the
  intended visual/behavioral result when actually read by a running
  Plasma session.
- That the `org.serein.desktop` Look-and-Feel KPackage's `metadata.json`
  shape exactly matches what Plasma 6.6's KPackage loader expects (the
  structure used here follows the documented KPackage JSON-metadata
  convention, but was not validated by loading it into a real
  `plasmashell`).
- That the SDDM `.conf.d` drop-in is honored in the exact precedence
  order assumed, on Ubuntu's packaged SDDM build specifically.
- Real screen-resolution/HiDPI/multi-monitor behavior of the panel layout
  — Plasma's own dynamic layout is relied on for this (per
  `docs/desktop/architecture.md`), but that reliance itself is untested
  here.

A live-VM (or Kubuntu 26.04 test image) validation pass is the
recommended next step before any of this ships to a real installer
(S7), and is called out as `LIVE_UBUNTU_PLASMA_VALIDATION=BLOCKED` in the
S1 completion report for exactly this reason.

## Package dependency closure

The desktop package groups in `package-strategy.md` are based on stable,
long-standing KDE/Debian package names, cross-checked against current
release notes and the Debian package tracker — but not against a
resolved `apt` dependency graph for Ubuntu 26.04 specifically. It is
possible the actual minimum-viable set needs one or two additions
(discovered only by installing on real hardware/VM) — this is an
accepted, documented risk rather than a hidden one.

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
