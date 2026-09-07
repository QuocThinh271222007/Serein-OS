# Veil (S6) Known Limitations

## No live validation performed this phase

Unlike S1/S5's WSL2 disposable-environment validation, S6/S6R were
implemented and unit-tested entirely against injected
`FakeCommandRunner`/fixture roots/homes - no live Ubuntu 26.04
environment was provisioned to install `tor`, run `torbrowser-launcher`,
or exercise a real `systemctl is-active tor@default.service`. Package
name/version and systemd-unit-filename claims in
`docs/veil/tor-strategy.md` and `docs/veil/whonix.md` are sourced from
live package-index/documentation research (Ubuntu's package search and
file-listing pages, the official Whonix KVM wiki page, the official Tor
Project download page - all fetched during S6/S6R), not from a
disposable-VM `apt install` the way S5's Finding 1-5 were. A future
corrective pass should do for S6 what S5R's
`docs/validation/s5/package-validation.md` did for S5: install
`tor`/`torsocks`/`nyx`/`obfs4proxy`/`torbrowser-launcher` in a
disposable environment and confirm the runtime-unit behavior, the
default `SocksPort`/`%include` state, and the launcher's actual
first-run behavior match what this documentation claims.

## Default Ubuntu `torrc`'s `%include` state is unconfirmed

S6R could not access an authoritative source confirming whether
Ubuntu 26.04's shipped default `/etc/tor/torrc` itself contains a
`%include /etc/tor/torrc.d` line (or equivalent) out of the box. This
does not affect correctness: `parse_tor_config()` only ever follows
whatever `%include` directives actually exist in the torrc it reads, so
it behaves correctly regardless of what the real shipped default turns
out to contain - this is a documentation-confidence gap, not a
detection-logic gap.

## `%include` support has real scope limits

`_resolve_lines()` implements a depth-limited (8 levels), cycle-guarded
recursive resolver for `%include <file>`/`%include <directory>` -
directory includes are non-recursive (only direct child files, sorted),
matching the "no recursion into subdirectories" conservative choice
made for host-safety reasons. It does not implement Tor's full config
grammar (e.g. `%include` with shell-style glob patterns, if Tor
supports them) - only plain file and directory paths.

## `obfs4proxy` detection is best-effort

`obfs4proxy` has no reliable `--version`/`-version` flag confirmed
live; `tor.py` probes it with `-version` and falls back to "any output
at all counts as installed" (the same tolerant rule
`serein.development.toolchains.probe_tool` already applies for tools
with inconsistent `--version` implementations). A build that prints
nothing to stdout/stderr before exiting would be under-detected as "not
installed" even if present - low-stakes, since `obfs4proxy` is
explicitly optional bridge/pluggable-transport tooling (Section 69),
never load-bearing for any `usable` verdict.

## The local SOCKS-listener heuristic is not perfect evidence

`_local_socks_listener_present()` checks specifically for port 9050
(Tor's compiled-in default). A Tor instance configured on a non-default
`SocksPort` (e.g. `9150`, the port Tor Browser's bundled Tor uses)
would not be detected by this check alone - by design, this is why a
custom SocksPort with no matching listener stays `usable=None`, never
`True` (S6R Corrective C, Section 22-23) - `docs/veil/tor-strategy.md`
documents this explicitly.

## Whonix domain-definition state is deliberately never determined

`gateway_domain_defined`/`workstation_domain_defined` are always
`None` - S6R considered a read-only `virsh list --all` probe but
rejected it: Serein has no safe way to strongly map a returned libvirt
domain name back to the *specific* verified artifact it claims to
represent (a domain named "Whonix-Gateway" could point its disk
anywhere). This is a deliberate, permanent conservative choice for the
current design, not a gap expected to close on its own - see
`docs/veil/whonix.md`.

## Whonix image path is the official documented default, not the only one

`~/.local/share/images/` is what Whonix's own KVM documentation
recommends and instructs users to move images to - but libvirt's
system-wide storage pool default (`/var/lib/libvirt/images/`) is also a
common real-world location for a system-level (non-session) libvirt
setup. S6 checks only the per-user documented path (Section 29's "no
filesystem-wide search" takes priority over covering every possible
libvirt pool location) - a system-level install would not be detected.
A future pass could add the system pool path as a second, still-exact,
still-non-recursive check if this proves to matter in practice.

## No kill-switch enforcement mechanism exists

See `docs/veil/kill-switch.md` - this is a deliberate phase boundary,
not an oversight: S6 has no Apply mechanism at all, so a kill switch
(which requires actual firewall/namespace enforcement) is out of scope
by construction, not merely unfinished.
