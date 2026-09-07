# Tor Client Strategy

## Package source (live-verified, 2026-09)

Ubuntu 26.04 ("resolute")'s own archive carries current, real packages
for all four Tor-adjacent components Section 8 asked to verify - no
Tor Project apt repository is added:

| Component | Ubuntu 26.04 package | Version (live-verified) |
|---|---|---|
| `tor` | `tor` | `0.4.9.x` series |
| `torsocks` | `torsocks` | `2.5.0-6` |
| `nyx` | `nyx` | `2.1.0-3build1` |
| `obfs4proxy` | `obfs4proxy` | `0.0.14-2build1` |

All four are `source_type="ubuntu-repository"` in
`src/serein/veil/components.py` - reducing supply-chain complexity by
staying on the distro archive, per the same "prefer apt when
reasonably current" default S5R's tool-source corrective established
for cyber tooling.

## Seven separate questions (Section 6), never collapsed

`TorStatusInfo` (`src/serein/veil/models.py`) keeps every signal
independent:

```
package_installed        - dpkg-confirmed or binary present
binary                    - `tor --version`
service_present/active     - systemctl evidence (see below)
config                      - torrc/torrc.d directive presence (see dns-leak-model.md)
socks_listener_detected      - local, read-only /proc/net/tcp[6] evidence
usable                        - the single canonical verdict below
```

## Tor package/service unit reality (Section 42-43)

The Debian/Ubuntu `tor` package's systemd unit naming is not hardcoded
to a single name: `src/serein/veil/tor.py`'s `_probe_tor_service` tries
`tor.service` first, then `tor@default.service`, using
`systemctl is-enabled <unit>` (a "not-found" result means "try the next
candidate") followed by `systemctl is-active <unit>` only for whichever
unit is actually present - a purely read-only, informational query,
never `enable`/`start`. If `systemctl` itself cannot be probed at all
(no systemd - many WSL configurations, some containers),
`service_present`/`service_active` are `None` ("unknown"), never
guessed `False` ("confirmed absent").

## The tri-state `usable` verdict

```
binary not installed                              -> False (high confidence)
service_present is None (no systemd probed)         -> None (low confidence)
service_present is False (systemctl ran, no unit)     -> False (medium confidence)
service_present True, service_active False              -> False (high confidence)
service_active True, SocksPort explicitly "0"             -> False (high confidence)
service_active True, SocksPort explicit non-zero OR
  a local listener detected on port 9050                    -> True (medium confidence)
service_active True, no directive, no listener evidence       -> None (low confidence)
```

"Tor binary present" never implies "Tor usable" (Section 7); "service
active" never implies "workspace safely routed" either - `usable=True`
here only ever means the Tor *client* itself is confirmed reachable
over SOCKS, nothing about any specific application's routing or DNS
behavior (see `docs/veil/dns-leak-model.md`).

## The local SOCKS-listener check (Section 45)

`_local_socks_listener_present` reads `/proc/net/tcp`/`/proc/net/tcp6`
(read-only) looking for a `LISTEN`-state (`0A`) entry on port 9050
(Tor's compiled-in default `SocksPort`). This never connects anywhere
(Section 44 - no `check.torproject.org`, no real SOCKS handshake). A
different process could theoretically be listening on 9050 (a false
positive) or Tor could be configured on a non-default port (a false
negative for this specific check) - which is exactly why it is only
ever *one* of two ways to reach `usable=True`, never the sole signal,
and an absent listener alone never drives `usable` to `False` (see the
table above - it falls to the honest "unknown" branch instead).

## torrc/torrc.d parsing (Section 39-41)

`parse_tor_config()` reads `/etc/tor/torrc` and every file in
`/etc/tor/torrc.d/` (read-only), extracting only a small, named set of
directives - `SocksPort`, `ControlPort`, `CookieAuthentication`,
`TransPort`, `DNSPort`, `DataDirectory`, and `Bridge` line *presence*.
It never reads or stores a raw directive value, a hashed control
password, a cookie file's contents, or a bridge line's actual text
(Section 39/92) - three directives get a tri-state
(`None`=no directive found, `True`=non-`"0"` value, `False`=explicit
`"0"`), three get presence-only booleans, and bridge lines get a single
presence boolean. An absent directive is never treated as "unsafe" -
Tor's own compiled-in defaults matter and are not asserted either way
(Section 41).
