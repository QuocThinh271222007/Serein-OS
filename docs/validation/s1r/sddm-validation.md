# S1R Validation E — SDDM Drop-in Behavior and Precedence

Environment: disposable `Ubuntu-26.04` WSL2 instance.

## Is `/etc/sddm.conf.d/*.conf` the real, supported mechanism?

Confirmed two ways:

**1. Authoritative documentation**, extracted directly from the real
`sddm` 0.21.0 package shipped in the Ubuntu 26.04 archive
(`sddm.conf.5` man page, downloaded and unpacked with `dpkg -x`, no
install required):

> Configuration loads all files in the configuration directories followed
> by the configuration file in the order listed below with the latter
> having highest precedence.
>
> - `/usr/lib/sddm/sddm.conf.d` — System configuration directory
> - `/etc/sddm.conf.d` — Local configuration directory
> - `/etc/sddm.conf` — Local configuration file for compatibility

This directly confirms `/etc/sddm.conf.d/*.conf` is real, upstream,
documented behavior — not an assumption — and that it takes precedence
over the package-shipped defaults in `/usr/lib/sddm/sddm.conf.d`.

**2. Real precedent**: `apt-file search /etc/sddm.conf.d` against the live
archive shows Ubuntu flavors already use exactly this mechanism for
exactly this purpose:

```
budgie-sddm-theme:        /etc/sddm.conf.d/50-ubuntu-budgie.conf
kubuntu-settings-desktop: /etc/sddm.conf.d/10-wayland.conf
kubuntu-settings-desktop: /etc/sddm.conf.d/20-kubuntu.conf
lubuntu-default-settings: /etc/sddm.conf.d/lubuntu_settings.conf
ubuntustudio-default-settings: /etc/sddm.conf.d/10-wayland.conf
```

`kubuntu-settings-desktop`'s own `.deb` was downloaded and extracted
(`dpkg -x`, no install) to inspect the real files:

`20-kubuntu.conf`:
```ini
[Autologin]
Relogin=false
Session=plasma
User=

[General]
HaltCommand=
RebootCommand=

[Theme]
Current=kubuntu
CursorSize=30
CursorTheme=breeze_cursors
Font=Noto Sans,10,-1,0,400,0,0,0,0,0,0,0,0,0,0,1
```

This confirms Serein's `desktop/sddm/serein.conf` uses the *identical*
section/key format (`[Theme] Current=`, `[Autologin] User=`/`Session=`)
that Kubuntu's own packaging uses — no invented keys, no Plasma-5-era
syntax.

## Precedence: does `90-serein.conf` do what the design expects?

Yes. Numeric-prefix drop-in files are read in lexical order with later
files taking precedence (confirmed by the man page's "latter having
highest precedence" plus Kubuntu's own `10-`/`20-` convention). Serein's
`90-serein.conf` sorts after Kubuntu's `10-wayland.conf` and
`20-kubuntu.conf`, so on a system where `kubuntu-settings-desktop` is also
present, Serein's `Current=breeze` would correctly override Kubuntu's
`Current=kubuntu` for the SDDM theme — the intended "Serein is the final
distribution-default layer" behavior, not an accident of file naming.

## Security check (static, against the file content — not interactive)

- `[Autologin] User=` and `Session=` are both explicitly empty in
  `desktop/sddm/serein.conf` — autologin is disabled, matching Kubuntu's
  own default posture (`User=` empty) and never more permissive.
  `S1R_AUTOLOGIN_DISABLED=true`.
- No `[General]` PAM-related or authentication key is present anywhere in
  the file — it touches only `[Theme]` and `[Autologin]`.
- No username, password, or bypass flag appears anywhere in the file.

## What could not be tested (BLOCKED, not a defect)

SDDM needs a real VT/DRM device to own a display and run its login
screen; WSL2 does not expose one, so the *interactive* login flow —
credential prompt rendering, successful login, logout, wrong-password
rejection — could not be exercised in this environment. This is a gap in
test coverage, not evidence of a problem: the drop-in mechanism, its
precedence, and its content are all confirmed correct against the real
package. Recorded as a non-blocking limitation in `known-blockers.md`.

## Verdict

```
S1R_SDDM_DROPIN_SUPPORTED=true
S1R_SDDM_THEME_PASS=true            (breeze theme package confirmed present: sddm-theme-breeze)
S1R_SDDM_AUTHENTICATION_PASS=PARTIAL  (static content verified safe; interactive login BLOCKED — no VT/DRM in WSL2)
S1R_AUTOLOGIN_DISABLED=true
```
