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
| `appearance` | `breeze`, `breeze-gtk-theme`, `plasma-integration` | Upstream Breeze (light/dark) and its GTK counterpart for visual consistency with any GTK apps, plus Qt/GTK desktop integration. |

**Deliberately excluded:** `plasma-session-x11` (matches Kubuntu 26.04's
own default of not installing it — see `wayland-strategy.md`),
`kubuntu-desktop` and any office/media/chat application, anything from S3
(editors, dev toolchains), S4 (CUDA/AI), or S5 (security tooling).

## Live validation (S1R)

The table above was originally drafted without access to a real Ubuntu
26.04 archive. S1R (`docs/validation/s1r/package-validation.md`) validated
it against a genuine Ubuntu 26.04 "resolute" archive (via an isolated
WSL2 instance) using `apt-cache policy` for every package plus
`apt-get install --simulate` for the full set together. One defect was
found and fixed: `breeze-gtk` does not exist in the archive — the actual
package is `breeze-gtk-theme`, which the table and
`src/serein/desktop/packages.py` now both use. All 17 packages exist and
the full set simulates cleanly with no conflicts, no removals, and no
unexpectedly large pulls. See `docs/validation/s1r/package-validation.md`
for exact versions and the simulated transaction summary.
