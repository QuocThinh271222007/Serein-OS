# Configuration Ownership Model

This is the critical requirement from the S1 brief: Serein must never
silently reset a user's personal KDE preferences on upgrade, and must be
able to state clearly which values it owns.

## The mechanism: `/etc/xdg` as a defaults layer, never `~/.config` writes

KDE's config stack (KConfig) reads `XDG_CONFIG_DIRS` (defaulting to
`/etc/xdg` when unset) as a **lower-priority layer beneath** each user's
`$XDG_CONFIG_HOME` (`~/.config`). This is existing, documented KDE/XDG
behavior, not a Serein invention:

- A value Serein ships in `/etc/xdg/kdeglobals` or `/etc/xdg/kwinrc`
  applies to every user — existing and future — **that hasn't already set
  that same key themselves.**
- The moment a user changes that setting from within Plasma, their change
  is written to `~/.config/kdeglobals`/`~/.config/kwinrc`, which always
  wins over the `/etc/xdg` layer from then on.
- Uninstalling Serein's desktop package removes the `/etc/xdg` files
  cleanly; user configs in `~/.config` are never touched, so nothing is
  lost either way.

**Consequently: Serein never writes to any user's `~/.config`, ever.**
There is no "copy defaults into home on login" step, no first-boot script
that touches `$HOME`, and no logic anywhere in this repository that
resolves a specific username or home directory. This directly satisfies
"no hardcoded developer username / no hardcoded home directory" as well
as the ownership requirement.

## First-login layout: KPackage "Look and Feel", not a home-directory copy

Panel layout isn't a simple key in `kdeglobals` — Plasma stores it as a
scripted layout template. Distributions set a default first-login layout
by shipping a **Look and Feel KPackage** (`org.serein.desktop`, see
`visual-design.md`) referenced from `/etc/xdg/kdeglobals`
(`LookAndFeelPackage=org.serein.desktop`). Plasma applies this only when a
user session has no existing layout of its own — again, an
existing-user-never-touched, new-user-gets-the-default mechanism, not a
copy operation Serein has to implement or maintain itself.

## What Serein owns vs. what users own

| Layer | Owner | Mechanism |
|---|---|---|
| `/etc/xdg/kdeglobals`, `/etc/xdg/kwinrc` | **Serein** (system defaults) | Shipped as package data; a user's `~/.config` equivalent always overrides it. |
| `org.serein.desktop` Look-and-Feel package | **Serein** (system defaults) | Applied only to sessions with no existing layout (first login). |
| SDDM config (`/etc/sddm.conf.d/90-serein.conf`) | **Serein** (system, drop-in) | A `.conf.d` drop-in, not an edit of `/etc/sddm.conf` itself — reversible by removing one file. |
| Konsole profile / color scheme | **Serein** (offered, not forced) | Installed as an available profile choice; Konsole's own default-profile selection is left to the user. |
| Anything under a user's `~/.config`, `~/.local/share` | **The user, always** | Serein reads none of it and writes none of it. |

## Config versioning

`src/serein/desktop/models.py:DESKTOP_CONFIG_VERSION = 1` is independent
of the Serein package version (`serein.__version__`), per the explicit S1
requirement — a desktop config migration in a future release does not
require a control-plane version bump, and vice versa. A future Apply step
would record the version it wrote at `/etc/serein/desktop/config-version`
(a single integer; see `detect.py`); a future migration path compares
that recorded version against `DESKTOP_CONFIG_VERSION` to decide whether
anything needs updating. No migration logic exists yet — S1 only
establishes the version constant and the marker file contract.

## Reversibility

Nothing S1 would install lives outside package-manager-tracked files or
the single `/etc/serein/desktop/config-version` marker:

- **Packages** Serein requested are exactly `desktop.packages.all_packages()`
  — removable with the package manager like any other package.
- **Config files** Serein introduces are the `/etc/xdg` drop-ins, the
  Look-and-Feel package, and the SDDM drop-in — each independently
  removable, none of them edits to a pre-existing Ubuntu-owned file (SDDM
  config is a `.conf.d` addition, not a patch to the base `sddm.conf`).
- **Serein does not uninstall or modify any package that predated it.**

Actual rollback *execution* is deferred to the S0 installer-contract's
Apply/Verify/Record steps (not implemented until a mutation engine
exists) — S1 only guarantees the ownership model above makes rollback
possible when that engine arrives.
