# ADR-0022: Tor Browser Preferred for Private Web Browsing

## Status

Accepted

## Context

An ordinary browser (Firefox/Chromium) can be pointed at a local Tor
SOCKS proxy with a few settings changes. This is technically simple but
is a materially weaker privacy posture than Tor Browser: Tor Browser
bundles anti-fingerprinting hardening (uniform window size,
letterboxing, first-party isolation, patched/restricted WebRTC,
NoScript defaults) that plain Firefox-plus-proxy does not have. A tool
that quietly recommends or automates "Firefox + SOCKS" as equivalent to
Tor Browser would be actively misleading users about their actual
fingerprint-resistance posture.

## Decision

- Serein's policy is `privacy-sensitive web browsing -> Tor Browser`,
  never "reconfigure the ordinary browser to route through Tor."
- `src/serein/veil/models.py` keeps `TorBrowserStatus` and
  `OrdinaryBrowserStatus` as entirely separate dataclasses with no
  shared fields - a capability built from one is never used to infer
  anything about the other.
- `docs/veil/tor-browser.md` documents the specific, concrete
  differences (window sizing, WebRTC, NoScript, first-party isolation)
  rather than asserting the distinction abstractly.
- Detection is limited to `torbrowser-launcher` (Ubuntu 26.04 universe:
  `0.3.9-1build1`, live-verified) - a "clean distro integration"
  (Section 19) that itself downloads and OpenPGP-signature-verifies the
  official torproject.org release; Serein never scans for an unpacked
  Tor Browser bundle in the user's home directory, and never downloads
  the tarball itself.
- A direct regression
  (`tests/test_veil.py::TestInvariants::test_tor_browser_never_equated_with_firefox_plus_socks`)
  asserts the `tor_browser` capability's `mechanism` field never
  mentions "firefox".

## Consequences

- Users get an accurate distinction instead of a false sense of parity
  between an ordinary browser routed through Tor and genuine Tor
  Browser hardening.
- `TorBrowserStatus.usable` stays `None` even with the launcher
  installed, since launcher presence proves the download/verification
  *mechanism* exists, not that the actual bundle has been fetched, run,
  or is currently up to date.
- A future workspace-activation Apply engine has a clear default to
  implement (launch Tor Browser) rather than needing to design a
  from-scratch Firefox-hardening profile that would duplicate work the
  Tor Project already does and maintains.

## Alternatives considered

**Automate a hardened Firefox profile as Serein's own "private
browsing" mechanism.** Rejected - substantial, continuously-maintained
security engineering effort (fingerprint resistance is an arms race)
that the Tor Project already does; duplicating it inside Serein would
be worse, not better, and risks a false sense of security if the
hardening drifts out of date.

**Treat any browser routed through SOCKS as sufficient and let the user
decide.** Rejected as too permissive for a tool that documents privacy
guarantees at all (Section 20/24) - the whole point of this subsystem
is refusing to blur that specific distinction.
