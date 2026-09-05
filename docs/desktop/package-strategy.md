# Desktop Package Strategy

## Rejected: a single kitchen-sink metapackage

`kubuntu-desktop` pulls in the full branded Kubuntu experience —
LibreOffice, Kontact, Konversation, Amarok, K3B, and more — none of which
is a desktop-*shell* requirement. Depending on it would mean Serein
silently owns package decisions (a full office suite, an IRC client, a
CD-burning tool) it never evaluated. Rejected per the explicit S1
instruction not to depend on an enormous kitchen-sink metapackage without
evaluating its contents.

## Rejected: aggressive minimalism

`kde-plasma-desktop` alone provides the bare shell but leaves out a
login manager, a network applet, an audio applet, and desktop-portal
integration — a user would get a Plasma session with no way to connect to
Wi-Fi or adjust volume from the panel. That's not a usable workstation
default either.

## Chosen: an explicit, curated package list, grouped by function

`src/serein/desktop/packages.py` is the single source of truth — a tuple
of named `PackageGroup`s, each with a rationale. `all_packages()`
flattens and sorts them; this flattened list is what
`profiles/desktop/desktop.profile.json`'s `packages` field and
`serein desktop plan` both use (a test asserts they stay in sync, so the
manifest can never silently drift from the code).

| Group | Packages | Why |
|---|---|---|
| `session` | `plasma-desktop`, `plasma-workspace`, `kwin-wayland`, `systemsettings` | The Plasma shell itself, its Wayland compositor, and its settings UI. |
| `login-manager` | `sddm`, `sddm-theme-breeze` | Upstream login manager with its upstream theme; configuration policy (no autologin, drop-in only) is in `configuration-ownership.md`. |
| `applications` | `dolphin`, `konsole`, `ark` | File manager, terminal, archive integration — the minimum a workstation needs before S3 adds development tooling. |
| `integration` | `xdg-desktop-portal-kde`, `plasma-nm`, `plasma-pa`, `print-manager`, `kinfocenter` | Desktop portals (file pickers for sandboxed/Flatpak apps), network and audio panel applets, print management, hardware info panel. Without these the panel looks complete but basic workstation actions (join Wi-Fi, change volume) don't work from the UI. |
| `appearance` | `breeze`, `breeze-gtk`, `plasma-integration` | Upstream Breeze (light/dark) and its GTK counterpart for visual consistency with any GTK apps, plus Qt/GTK desktop integration. |

**Deliberately excluded:** `plasma-session-x11` (matches Kubuntu 26.04's
own default of not installing it — see `wayland-strategy.md`),
`kubuntu-desktop` and any office/media/chat application, anything from S3
(editors, dev toolchains), S4 (CUDA/AI), or S5 (security tooling).

## What is *not* verified against a live Ubuntu 26.04 archive

This development environment has no access to a real Ubuntu 26.04
system or `apt-cache`, so exact `Depends:`/`Recommends:` relationships for
each package above were not queried package-by-package against the live
archive. What *is* verified (via kubuntu.org's own 26.04 release notes and
the Debian package tracker) are: the Plasma 6.6/Frameworks 6.24 version
baseline, the Wayland-default/X11-not-installed policy, and the specific
package names listed in the table, which have been stable, unversioned
KDE/Debian package names across the Plasma 5→6 transition. Confirming
exact dependency closure is listed in `known-limitations.md` as work for
a live-VM validation pass.
