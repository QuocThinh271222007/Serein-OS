# Tor Browser Strategy

## Tor Browser ≠ Firefox + Tor proxy

Tor Browser bundles anti-fingerprinting and privacy hardening that
plain Firefox routed through a SOCKS proxy does not have: a uniform
window size (fingerprint resistance), letterboxing, first-party
isolation, patched/restricted WebRTC, NoScript defaults, and a curated
extension policy. Routing traffic through Tor does not, by itself,
grant any of that (Section 20). Serein's policy (Section 17, ADR-0022)
is:

```
privacy-sensitive web browsing -> Tor Browser
```

never "teach Serein to recreate Tor Browser via Firefox settings."
`src/serein/veil/browser.py` and `capabilities.py` keep
`tor_browser`/`ordinary_browser` as genuinely separate models -
neither is ever folded into the other, and the `tor_client`/
`tor_browser` capabilities never imply each other either (Section 54).

## Current official distribution (verified 2026-09)

Live research against `torproject.org/download/` confirms the official
Linux distribution model has not changed materially: a signed
`tor-browser-linux-x86_64-<version>.tar.xz` tarball with a `.asc`
signature, extracted and run locally - no apt repository, no Flatpak,
no Snap.

Ubuntu 26.04's universe repository does carry `torbrowser-launcher`
(`0.3.9-1build1`, live-verified) - a well-established, community-
maintained helper that itself downloads and OpenPGP-signature-verifies
the *official* torproject.org release on the user's behalf. This is
the "clean distro integration" Section 19 allows in place of treating
the raw tarball as the only acceptable mechanism.

## What Serein detects

`detect_tor_browser_status()` only checks for `torbrowser-launcher`
(via `probe_tool` + a dpkg-query fallback) - it never scans the user's
home directory for an already-unpacked Tor Browser bundle (generalizing
Section 29's "no filesystem-wide search" rule to browser detection
too). Launcher presence is a real signal that the *mechanism* to get an
official, verified Tor Browser exists; it is not proof the actual
browser bundle has ever been downloaded, verified, or run -
`TorBrowserStatus.usable` is therefore always `None`, regardless of
`launcher_installed` (Section 19: install ownership stays
user-managed/official-upstream - Serein documents, it does not
automate the first run).

## Install ownership

```
mechanism        torbrowser-launcher (Ubuntu universe, apt-installable)
actual browser    downloaded + signature-verified by the launcher on first
                   user-initiated run - Serein never triggers this
alternative        the official torproject.org tarball, equally valid,
                     entirely user-managed, never downloaded by Serein
```

`serein veil plan tor|workspace` proposes `browser.tor_browser` as an
`APPLY`/`NOOP` on the *launcher package* only (`workspace` component -
installing a browser-launcher helper is a workspace-tier action just
like the Tor client itself) - never a "download Tor Browser" action.
