# ADR-0005: KDE Plasma as Serein's Desktop Environment

## Status

Accepted

## Context

S1 needs a graphical workstation environment for Serein. Serein's target
users (AI/dev/security workstation users, per `docs/roadmap.md`) need a
desktop that is configurable without fighting the shell, keeps GTK and Qt
applications equally first-class, and doesn't fight Serein's "quiet, dark,
low-distraction" visual goal (`docs/desktop/visual-design.md`). The
options considered were the three major desktop environments Ubuntu
flavors ship: KDE Plasma, GNOME, and XFCE.

## Decision

Serein Desktop is built on **KDE Plasma** (6.6 as shipped by Kubuntu
26.04 LTS), with KWin as its Wayland-native compositor and SDDM as its
login manager, configured — not forked — via `/etc/xdg` defaults and one
Look-and-Feel package (`docs/desktop/configuration-ownership.md`).

## Trade-off analysis

### KDE Plasma (chosen)

- **For:** Deep, first-class configurability through standard mechanisms
  (KConfig cascading, Look-and-Feel packages, color schemes) that let
  Serein express its identity *without* patching or replacing shell code
  — directly serving Integrate → Measure → Replace. Wayland support is
  mature and, per Kubuntu 26.04, is now the default and only supported
  session, aligning with Serein's Wayland-first goal. Widget/panel model
  supports the exact minimal layout Serein wants (`docs/desktop/
  architecture.md`) without extension hunting. Native Qt; GTK apps run
  fine via `breeze-gtk`.
- **Against:** More moving parts than GNOME/XFCE (KWin + Plasma shell +
  KConfig layers is a bigger surface than GNOME Shell's more monolithic
  design). Requires deliberate curation to avoid the
  kitchen-sink-metapackage trap (`docs/desktop/package-strategy.md`).

### GNOME

- **For:** Strong Wayland-native design (arguably even more mature
  historically), polished default aesthetic, large Ubuntu-ecosystem
  familiarity (it's Ubuntu's own default desktop).
- **Against:** GNOME's configuration model deliberately discourages the
  kind of per-distro customization Serein wants (opinionated "no
  settings" philosophy; meaningful changes typically require GNOME Shell
  extensions, which are more fragile across GNOME version upgrades than
  KDE's Look-and-Feel/color-scheme mechanisms). Achieving Serein's minimal
  bottom-panel layout would fight the shell's default top-bar/dock model
  rather than being a first-class supported configuration.

### XFCE

- **For:** Very lightweight, simple, highly stable configuration format
  (plain XML), minimal resource footprint.
- **Against:** Wayland support is not production-mature as of this
  writing — XFCE remains substantially X11-oriented, directly conflicting
  with Serein's Wayland-first policy (`docs/desktop/wayland-strategy.md`).
  Visual/UX polish is comparatively dated relative to Serein's "premium,
  clean, technical" target without significant custom work — work that
  would violate the "90% upstream" principle since XFCE's out-of-the-box
  look needs more correction, not less, to reach that bar.

## Consequences

- Serein Desktop inherits Plasma's release cadence and Kubuntu's
  packaging — a future Plasma major-version change may require a
  `desktop_config_version` migration (`docs/desktop/
  configuration-ownership.md`).
- GTK application theming depends on `breeze-gtk` staying maintained
  upstream; if it doesn't, that's a concrete, measurable reason to
  revisit (Integrate → Measure → Replace), not a reason to preemptively
  hedge now.
- Committing to Wayland-first means any future NVIDIA-specific Wayland
  compatibility work becomes S2's problem to solve, not S1's to avoid by
  picking X11.

## Alternatives considered

GNOME and XFCE, both evaluated above and rejected for this phase. Neither
rejection is permanent — per
[ADR-0002](0002-upstream-first.md), a future replacement is possible if a
measured need arises (e.g., a future Serein variant explicitly optimized
for minimal resource footprint might reconsider XFCE once its Wayland
story matures).
