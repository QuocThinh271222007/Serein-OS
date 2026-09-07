# Veil (S6) Known Limitations

## No live validation performed this phase

Unlike S1/S5's WSL2 disposable-environment validation, S6 was
implemented and unit-tested entirely against injected
`FakeCommandRunner`/fixture roots/homes - no live Ubuntu 26.04
environment was provisioned to install `tor`, run `torbrowser-launcher`,
or exercise a real `systemctl is-active tor.service`/`dumpcap`-style
capture. Package name/version claims in `docs/veil/tor-strategy.md` and
`docs/veil/whonix.md` are sourced from live package-index/documentation
research (Ubuntu's package search, the official Whonix KVM wiki page,
the official Tor Project download page - all fetched during this
implementation pass), not from a disposable-VM `apt install` the way
S5's Finding 1-5 were. A future corrective pass should do for S6 what
S5R's `docs/validation/s5/package-validation.md` did for S5: install
`tor`/`torsocks`/`nyx`/`obfs4proxy`/`torbrowser-launcher` in a
disposable environment and confirm the systemd unit name, the default
`SocksPort`/`ControlPort` state, and the launcher's actual first-run
behavior match what this documentation claims.

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
would not be detected by this check alone - `tor.py`'s docstring and
`docs/veil/tor-strategy.md` document this explicitly; it is why the
listener check is only ever combined evidence alongside the `torrc`
`SocksPort` directive, never sole proof either way.

## `torrc.d` directive precedence is not modeled

Real Tor config resolution has directive-ordering/override semantics
across `torrc` and `torrc.d/*.conf` (later files can override earlier
ones for some directives). `parse_tor_config()` takes the *first*
matching directive it finds across the concatenated line list - correct
for detecting *presence*, but not a faithful simulation of Tor's actual
config-merge behavior. This is acceptable for S6's boolean-presence
questions (Section 39-41) but should not be read as a full torrc
parser.

## No systemd-unit research beyond `tor.service`/`tor@default.service`

Section 43 asked for verification of "current Ubuntu 26.04 behavior";
this pass could not access an authoritative source confirming which of
the two candidate unit names Ubuntu 26.04's actual `tor` package
postinst enables by default (Debian's own documentation is ambiguous
between versions). `_probe_tor_service()` tries both, in that order,
which is safe (never wrong, at worst slightly redundant) but not
independently confirmed against a live Ubuntu 26.04 install this pass.

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
