# Veil Threat Model

## What Veil helps with

- **Network-destination privacy via Tor.** A usable Tor client (real,
  read-only evidence: active service + a configured/detected SOCKS
  listener - see `docs/veil/tor-strategy.md`) hides which destination
  an application connects to from the local network/ISP, routing
  through Tor's relay network instead.
- **Workspace separation.** A future isolated privacy workspace (S6
  only plans this - see `docs/veil/private-workspace.md`) is intended
  to keep privacy-sensitive activity out of the ordinary host session:
  its own browser profile, its own routing, no shared history.
- **Browser-state separation.** Tor Browser's own profile is
  independent of any ordinary browser profile on the host - no shared
  cookies, extensions, or history by design.
- **Host/privacy workflow separation.** The three-tier model (Normal
  Host / Veil Workspace / Whonix) keeps privacy-sensitive work from
  silently bleeding into ordinary host use, and vice versa.

## What Veil does NOT automatically solve

- **Endpoint compromise.** Malware on the host or in a VM sees
  everything regardless of network routing.
- **Malicious browser extensions.** Tor routing does not vet or sandbox
  extensions; Tor Browser's own defaults (few/no extensions) are the
  actual mitigation, not anything Serein adds.
- **Identity correlation.** Logging into an identifying account (email,
  social media, a named service) over Tor links that session to your
  identity regardless of network anonymity - Serein documents this, it
  does not moralize about it (Section 73).
- **Account logins.** Same point, explicitly: network anonymity cannot
  override application/account identity.
- **Browser fingerprint mistakes outside Tor Browser.** An ordinary
  browser routed through SOCKS is not Tor Browser and does not get its
  anti-fingerprinting defenses (window size normalization, WebRTC
  handling, letterboxing, NoScript defaults) - see
  `docs/veil/tor-browser.md`.
- **Malware.** Veil is a network-routing/isolation model, not an
  antivirus or sandboxing product.
- **Hardware/firmware compromise.** Out of scope for any software-layer
  privacy tool.
- **Global passive adversary guarantees.** Tor's own threat model does
  not claim protection against an adversary that can observe both ends
  of a connection simultaneously; Serein inherits that limitation and
  does not claim otherwise.

## Why "installed" is never "safe"

Every module in this subsystem enforces one discipline: a boolean
presence signal (a package installed, a binary on PATH, a service
active) is never promoted to a privacy/anonymity claim without direct,
read-only, positive evidence of the specific property being claimed.
See the invariant chain in `docs/veil/architecture.md`'s "no false
privacy claims" discussion and the concrete state machines in
`docs/veil/tor-strategy.md`, `docs/veil/dns-leak-model.md`, and
`docs/veil/kill-switch.md`.
