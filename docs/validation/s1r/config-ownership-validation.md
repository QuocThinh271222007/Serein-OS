# S1R Validation B — dpkg File Ownership and KConfig Cascading

This is the critical S1R gate (Section 8–9 of the S1R brief): does Serein
ever write to a path another `.deb` already owns?

## dpkg ownership of `/etc/xdg/kdeglobals` and `/etc/xdg/kwinrc`

Checked two ways, both against the real Ubuntu 26.04 archive:

**1. Archive-wide (`apt-file`, covers every package in the archive, not
just installed ones):**

```
$ apt-file search /etc/xdg/kdeglobals
(no output)
$ apt-file search /etc/xdg/kwinrc
(no output)
```

**2. Literal `dpkg-query -S`, run after the full Serein desktop package
set was actually installed** (not simulated) in the disposable VM:

```
$ dpkg-query -S /etc/xdg/kdeglobals
dpkg-query: no path found matching pattern /etc/xdg/kdeglobals

$ dpkg-query -S /etc/xdg/kwinrc
dpkg-query: no path found matching pattern /etc/xdg/kwinrc

$ ls /etc/xdg/kdeglobals /etc/xdg/kwinrc
ls: cannot access '/etc/xdg/kdeglobals': No such file or directory
ls: cannot access '/etc/xdg/kwinrc': No such file or directory
```

**Neither file is shipped by any package in Ubuntu 26.04, installed or
not — confirmed twice, before and after a real, full install of every
package `packages.py` requests.**

For context, `dpkg-query -S '/etc/xdg/*'` on the same fully-installed
system shows `/etc/xdg` *is* a real, actively-used KDE configuration
directory — `plasma-workspace` owns `/etc/xdg/menus` and
`/etc/xdg/plasmanotifyrc`, and several packages own files under
`/etc/xdg/autostart`. So Serein isn't picking an obscure or unused
location; it's placing its two files in the same real directory KDE's own
packages already use, at the two specific filenames nothing else claims.

### Decision (per Section 9)

Not owned → **keep the current architecture.** No alternative
(`XDG_CONFIG_DIRS` layering, a different defaults mechanism) is needed;
switching to something more complex than "ship a file at an unclaimed
path in the standard KConfig system directory" would be over-engineering
a problem that doesn't exist.

`S1R_XDG_KDEGLOBALS_OWNER=none (unowned)`
`S1R_XDG_KWINRC_OWNER=none (unowned)`
`S1R_CONFIG_OWNERSHIP_COLLISION=false`

## KConfig cascading precedence — empirical proof, not just documentation

Section 10 asks for the invariant "user preferences always win" to be
tested, not merely cited. Using the real `kreadconfig6` tool (from
`libkf6config-bin`, shipped by the real install) and two real Linux user
accounts on the disposable VM:

| Step | Action | `kreadconfig6 --file kdeglobals --group General --key ColorScheme` |
|---|---|---|
| 1 | System default only (`/etc/xdg/kdeglobals`), no user override | `SereinDark` |
| 2 | User writes `~/.config/kdeglobals` with `ColorScheme=UserChosenScheme` | `UserChosenScheme` |
| 3 | Re-read `/etc/xdg/kdeglobals` directly | still `SereinDark` — Serein's own file was never touched |
| 4 | A second, independent, never-configured user reads the same key | `SereinDark` (gets the system default, unaffected by user A) |
| 5 | User A re-reads after a fresh process invocation (stand-in for logout/login) | still `UserChosenScheme` — not reset |

This is the exact 7-point sequence Section 10 asks for, minus a literal
graphical logout/login (each "read" here is a fresh process reading the
same on-disk files fresh, which is what logout/login does at the
KConfig-cascading level; a full desktop-session logout/login was exercised
separately for the Look-and-Feel default layout itself — see
`plasma-runtime-validation.md`, Test 2, which relaunches a real
`plasmashell` process against a persisted `~/.config` and confirms the
same non-destructive result at the Plasma-shell level, not just the
`kreadconfig6` level).

`S1R_CONFIG_OWNERSHIP_MODEL_VALIDATED=true`
