# Desktop Architecture (S1)

## Verified upstream facts this phase is built on

Encoded assumptions were checked against current sources rather than
carried over from older Ubuntu/KDE tutorials:

- **Kubuntu 26.04 LTS** ("Resolute Raccoon", released 2026-04-23) ships
  **KDE Plasma 6.6**, Qt 6.10.2, KDE Frameworks 6.24.0, on kernel 7.0.
  (kubuntu.org release notes)
- **The Plasma Wayland session is the default and only supported session**
  in Kubuntu 26.04. The X11 session (`plasma-session-x11`) exists in the
  Ubuntu archive but is **not installed by default and is not supported by
  the Kubuntu team.** This is an inversion of older Ubuntu releases, where
  X11 was default and Wayland was opt-in — do not carry that assumption
  forward. (kubuntu.org release notes)
- Ubuntu/Debian ship tiered Plasma metapackages: `kde-plasma-desktop`
  (minimal shell only), `kde-standard`, `kde-full` (adds games/education),
  and the separate `kubuntu-desktop` (the full *branded* Kubuntu
  experience — LibreOffice, Kontact, Konversation, Amarok, K3B, etc.).
  `kubuntu-desktop` is a kitchen-sink metapackage, not a "minimal Plasma"
  package — Serein does not depend on it (see `package-strategy.md`).
- Stable, currently-packaged component names confirmed against the
  Debian package tracker and search of current KDE/Debian packaging
  discussion: `plasma-desktop`, `plasma-workspace`, `sddm`,
  `sddm-theme-breeze`, `plasma-nm`, `plasma-pa`, `xdg-desktop-portal-kde`.
- KDE's config system treats `/etc/xdg/*` as a **lower-priority defaults
  layer** beneath each user's `~/.config/*` (`XDG_CONFIG_DIRS`, defaulting
  to `/etc/xdg` when unset). A distro default placed there is never
  overwritten by, and never overwrites, a user's own setting — see
  `configuration-ownership.md`.
- Plasma's KPackage "Look and Feel" mechanism bundles a panel layout
  template, color scheme, and icon theme reference, and is what
  distributions use to set a default first-login layout without touching
  existing user sessions.

## Why `desktop.profile.json` has no `hardware_conditions`

The desktop profile's `hardware_conditions` field is intentionally empty:
Serein Desktop has no GPU/RAM/architecture precondition beyond what the S0
foundation doctor already checks (x86_64, a working Linux host). Any
compatible Serein host qualifies; hardware-driven *tuning* (not
eligibility) is S2's concern, not a gate S1 needs to declare.

## Why KDE Plasma

See [ADR-0005](../adr/0005-kde-plasma-desktop.md) for the full trade-off
analysis against GNOME and XFCE.

## Stack

```
Ubuntu 26.04 LTS
      |
   Wayland                (default and only supported compositor protocol)
      |
  KDE Plasma 6.6           (workspace shell)
      |
     KWin                 (compositor/window manager, Wayland-native)
      |
     SDDM                 (login manager, upstream Breeze theme)
      |
Breeze-based Serein configuration   (this phase's actual contribution)
```

Every layer above "Serein configuration" is unmodified upstream Ubuntu
packaging. S1 does not fork, patch, or replace any of it — it only adds a
declarative package manifest, a small number of `/etc/xdg` default-config
files, one Look-and-Feel package, an SDDM config drop-in, and a Konsole
profile. See `docs/architecture/principles.md` (Integrate → Measure →
Replace) — nothing here has crossed into "replace" territory.

## Desktop subsystem (`src/serein/desktop/`)

Mirrors the S0 hardware module's architecture: every filesystem check
takes an injectable `root: Path` (defaulting to `/`), and session
detection takes an injectable `env: Mapping[str, str]` (defaulting to
`os.environ`), so nothing here requires a live KDE session, root, or even
Linux to test.

```
desktop/
├── models.py    dataclasses: DesktopAvailability, SessionInfo,
│                ConfigState, DesktopStatusReport, PlanStep, DesktopPlan
├── detect.py    binary presence (installed) + XDG session env (running)
│                + config-version marker (Serein-managed or not)
├── packages.py  canonical package groups — single source of truth,
│                flattened into profiles/desktop/desktop.profile.json
├── config.py    canonical list of config resources this repo ships
│                under desktop/, with their real target paths
├── plan.py      build_desktop_plan() — deterministic, pure function
│                of packages.py + config.py, no host I/O
├── status.py    build_desktop_status() — read-only status report
└── doctor.py    desktop-specific PASS/WARN/FAIL/SKIP checks, reusing
                 serein.doctor.models so desktop doctor output validates
                 against the same schemas/doctor-report.schema.json
```

## Installed vs. running vs. Serein-managed

Three questions this subsystem answers separately, per
`docs/architecture/doctor-contract.md`'s "don't confuse missing with
broken" principle:

1. **Is a component installed?** (`detect.detect_availability`) — checks
   for `plasmashell`/`kwin_wayland`/`kwin_x11`/`sddm` under standard bin
   directories relative to `root`.
2. **Is a graphical session currently active, and which kind?**
   (`detect.detect_session`) — reads `XDG_SESSION_TYPE`/
   `XDG_CURRENT_DESKTOP` from `env`. Meaningless (and reported as such)
   outside a live graphical login.
3. **Did Serein apply its desktop configuration to this host?**
   (`detect.detect_config_state`) — checks for a config-version marker at
   `/etc/serein/desktop/config-version`, written only by a future Apply
   step (S1 never writes it). Its presence is what lets doctor distinguish
   "not installed yet" (marker absent, component absent — expected, SKIP)
   from "broken installation" (marker present, component absent — FAIL).
