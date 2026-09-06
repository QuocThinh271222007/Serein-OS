# S1R Validation C/D — Look-and-Feel KPackage, Panel Layout, Color Scheme, Konsole, KWin

Environment: disposable `Ubuntu-26.04` WSL2 instance, with the full Serein
desktop package set actually installed (not simulated) and Serein's
`desktop/` resources staged at their real target paths
(`/etc/xdg/kdeglobals`, `/etc/xdg/kwinrc`, `/usr/share/color-schemes/
SereinDark.colors`, `/usr/share/konsole/Serein.profile` +
`SereinDark.colorscheme`, `/usr/share/plasma/look-and-feel/
org.serein.desktop/`).

## Look-and-Feel KPackage (Section 11–12)

Installed with the real upstream tool, not just file-copied:

```
$ kpackagetool6 -t Plasma/LookAndFeel -g -i /tmp/org.serein.desktop
Successfully installed /usr/share/plasma/look-and-feel/org.serein.desktop/

$ kpackagetool6 -t Plasma/LookAndFeel -g -s org.serein.desktop
Showing info for package: org.serein.desktop
  Name       : Serein Dark
  Description: Serein's default quiet, dark, workstation-oriented panel layout...
  Plugin     : org.serein.desktop
  Author     : Serein OS project
  Path       : /usr/share/plasma/look-and-feel/org.serein.desktop/

$ kpackagetool6 -t Plasma/LookAndFeel -g -l | grep serein
org.serein.desktop
```

**Result: `metadata.json` is accepted exactly as authored by real Plasma
6.6 KPackage tooling.** No metadata errors, no rejected fields. The
`KPackageStructure`/`KPlugin.{Id,Name,Description,Authors,Icon,Version}`
shape used in `desktop/plasma/look-and-feel/org.serein.desktop/
metadata.json` is confirmed current for Plasma 6, not a Plasma-5 holdover
— nothing needed correcting here.

`S1R_KPACKAGE_METADATA_VALID=true`, `S1R_LOOKANDFEEL_DISCOVERED=true`.

## Panel layout — real runtime evidence (Section 13–15)

A genuine Plasma Wayland session could not use WSLg's own compositor as
the nested Wayland host: `kwin_wayland_backend: wp_single_pixel_buffer_
manager_v1 isn't supported by the host compositor` — WSLg's bundled
compositor doesn't implement a Wayland protocol extension KWin 6.6's
nested backend requires. This is a documented WSLg limitation, not a
Serein defect (see `known-blockers.md`).

Instead, **KWin's own `--virtual` backend** — the same headless
framebuffer backend upstream KWin uses for its own automated tests — was
used to run a real, complete `plasmashell` session with no host-compositor
dependency at all:

```
dbus-run-session -- kwin_wayland_wrapper --virtual --width 1920 --height 1080 -- plasmashell
```

This is genuine Tier A-equivalent evidence for the shell/compositor layer
(real `kwin_wayland` + real `plasmashell` processes, real KPackage
resolution, real KConfig writes) — the one thing it cannot exercise is
SDDM's own display/login step, covered separately in `sddm-validation.md`.

### Test 1 — fresh user, first launch (`serein-fresh-1`, `~/.config` empty)

Resulting `~/.config/plasma-org.kde.plasma.desktop-appletsrc` (real file
written by real `plasmashell`):

```ini
[Containments][2]
formfactor=2
location=4
plugin=org.kde.panel

[Containments][2][General]
AppletOrder=3;4;5;6;18
```

Cross-referencing the applet IDs against the same file's `[Containments]
[2][Applets][N]` blocks:

| Applet ID | Plugin |
|---|---|
| 3 | `org.kde.plasma.kickoff` |
| 4 | `org.kde.plasma.icontasks` |
| 5 | `org.kde.plasma.marginsseparator` |
| 6 | `org.kde.plasma.systemtray` |
| 18 | `org.kde.plasma.digitalclock` |

`location=4` is Plasma's `BottomEdge` location constant. **This is exactly
the intended layout** (`desktop/plasma/look-and-feel/org.serein.desktop/
contents/layouts/org.kde.plasma.desktop-layout.js`) — bottom position,
correct widgets, correct order — proving Plasma actually executed the
layout script, not merely that the script file exists on disk. Only one
panel containment exists (`[Containments][1]` is the ordinary desktop/
folder containment Plasma always creates, `formfactor=0`) — no duplicate
panel, no leftover default upstream panel.

One pre-existing, Serein-unrelated packaging warning was observed:
`kf.package: Could not find required file "mainscript" for package
"org.kde.plasma.icontasks"` — a QML entry-point warning about the
`icontasks` plasmoid's own upstream package on this Ubuntu build, emitted
regardless of which Look-and-Feel package is active. It did not prevent
`icontasks` from being added to the panel per the appletsrc above, and is
out of Serein's control (`icontasks` ships as part of `plasma-desktop`,
unmodified by Serein). No error or warning referencing `org.serein.desktop`
or the layout script itself appeared in any of the three session logs.

`S1R_PANEL_LAYOUT_APPLIED=true`, `S1R_FIRST_LOGIN_BEHAVIOR_PASS=true`.

### Test 2 — same user, simulated customization, relaunch

`AppletOrder` was edited on disk (`3;4;5;6;18` → `18;3;4;5;6`, simulating
a user dragging the clock to the front) and the session relaunched **for
the same user, without clearing `~/.config`**:

```
--- AppletOrder after relaunch ---
AppletOrder=18;3;4;5;6
--- AppletOrder after clean shutdown ---
AppletOrder=18;3;4;5;6
```

**The customization survived a real second session launch and clean
shutdown unchanged.** Serein's Look-and-Feel default is a first-login-only
mechanism (per KDE's own KPackage semantics, `docs/desktop/
configuration-ownership.md`); this run proves that in practice, not just
in documentation.

### Test 3 — second, independent fresh user (`serein-fresh-2`)

```
AppletOrder=3;4;5;6;18
[Containments][2]
formfactor=2
```

An unrelated fresh account gets the same Serein default layout,
unaffected by `serein-fresh-1`'s customization — confirming "distribution
default + per-user ownership after first use" as a real, working model,
not merely a design intent.

`S1R_EXISTING_USER_PRESERVED=true`.

### What this does not prove

- No physical/virtual GPU display was rendered to a screen — this is
  headless framebuffer evidence (real widget/config state, not a visual
  render). Screenshots were not produced; `S1R_HIDPI_VALIDATION=BLOCKED`
  and `S1R_MULTIMONITOR_VALIDATION=BLOCKED` (Section 24/25) since scaling
  and multi-output behavior require an actual rendered display, which
  `--virtual` mode alone does not exercise meaningfully.
- SDDM did not launch this session — see `sddm-validation.md` for what was
  and wasn't verified there.

## Color scheme (Section 21)

```
$ plasma-apply-colorscheme --list-schemes
 * BreezeClassic
 * BreezeDark
 * BreezeLight
 * Oxygen
 * OxygenCold
 * SereinDark (current color scheme)
```

`SereinDark.colors` parses without error and is correctly recognized
alongside the stock Breeze schemes by the real `plasma-apply-colorscheme`
tool; it also reports as the currently-active scheme, confirming
`/etc/xdg/kdeglobals`'s `ColorScheme=SereinDark` default was read
correctly. No redesign was needed — the file uses the same section
layout as `BreezeDark.colors` in the same directory.

`S1R_COLOR_SCHEME_LOAD_PASS=true`.

## Konsole (Section 22)

```
$ konsole --profile Serein -e /bin/true
KONSOLE_EXIT=0
```

Launched (via WSLg's X11 socket) with the Serein profile and color scheme
staged at their real target paths; exited cleanly with no parse warnings
on stderr. `Serein.profile` references no font (by design — see
`docs/desktop/visual-design.md`) and no resource that doesn't exist.

`S1R_KONSOLE_PROFILE_LOAD_PASS=true`.

## KWin config (Section 23)

`desktop/kwin/kwinrc`'s `[Compositing]`, `[Desktops]`, and `[Windows]`
keys were staged at `/etc/xdg/kwinrc` and live for all three real
`kwin_wayland` sessions above. Across all three sessions' full logs, zero
warnings referencing any of `AnimationSpeed`, `WindowsBlockCompositing`,
`BorderlessMaximizedWindows`, `FocusPolicy`, `RollOverDesktops`, or
`Desktop_<N>_Name` appeared, and no "unknown key" diagnostics were logged
by KWin. This is not the same as proving each key changes rendered
behavior (that needs a visible display — BLOCKED, see above), but it
does confirm KWin 6.6 parses the file and none of these keys are rejected
or flagged as obsolete. No key was removed.

`S1R_KWIN_CONFIG_PARSE_PASS=true`.
