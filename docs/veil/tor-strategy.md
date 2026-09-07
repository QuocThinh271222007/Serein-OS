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

## Six separate questions, never collapsed

`TorStatusInfo` (`src/serein/veil/models.py`) keeps every signal
independent:

```
package_installed        - dpkg-confirmed or binary present
binary                    - `tor --version`
service                    - TorServiceStatus (master vs. runtime - see below)
config                      - torrc/%include directive evaluation (see below)
socks_listener_detected      - local, read-only /proc/net/tcp[6] evidence
usable                        - the single canonical verdict below
```

## Tor systemd packaging reality (S6R Corrective A, live-verified)

Ubuntu 26.04's `tor` package ships exactly three systemd unit files
(confirmed against the package's own file listing):

```
tor.service          - top-level/master orchestration unit
tor@.service          - uninstantiated multi-instance template
tor@default.service     - the concrete default-instance unit
```

**Only `tor@default.service` is real Tor-daemon runtime evidence.** An
earlier S6 pass let a bare `tor.service active` result satisfy runtime-
active evidence; this was incorrect and has been corrected.
`TorServiceStatus` keeps the two apart explicitly:

```
master_unit_present/master_unit_active     - tor.service (diagnostic only, never runtime proof)
runtime_unit_present/runtime_unit_active      - tor@default.service (the real evidence)
runtime_unit_name                              - "tor@default.service" once found, else ""
service_present/service_active                  - properties that ARE runtime_unit_present/active
                                                    (every other module reads these two)
```

`src/serein/veil/tor.py`'s `_probe_tor_service` probes `tor.service`
(master, diagnostic-only) and `tor@default.service` (runtime,
authoritative) with `systemctl is-enabled`/`systemctl is-active` -
purely read-only, never `enable`/`start`/`restart`. If `systemctl`
itself cannot be probed at all (no systemd - many WSL configurations,
some containers), every field is `None` ("unknown"), never guessed
`False` ("confirmed absent"); if systemctl runs but the runtime unit
genuinely does not exist, `runtime_unit_present` is a definite `False`.

## The tri-state `usable` verdict (S6R Corrective C)

```
binary not installed                                       -> False (high confidence)
runtime_unit_present is None (no systemd probed)              -> None (low confidence)
runtime_unit_present is False (systemctl ran, no runtime unit)  -> False (medium confidence)
runtime_unit_present True, runtime_unit_active False               -> False (high confidence)
runtime_unit_active True, SocksPort explicitly "0"                    -> False (high confidence)
runtime_unit_active True, local listener confirmed on port 9050          -> True (medium confidence)
runtime_unit_active True, SocksPort configured but no confirmed listener    -> None (low confidence)
runtime_unit_active True, no directive, no listener evidence                  -> None (low confidence)
```

Configuration intent is never runtime proof by itself: "SocksPort
configured" alone - even an explicit, enabled `SocksPort 9050` line -
never promotes `usable` to `True` without a real, local listener
confirmation. `usable=True` requires BOTH the Tor daemon *runtime* unit
confirmed active AND a real listener detected - "tor binary present"
alone, "tor.service active" alone, or "SocksPort configured" alone all
never imply usability (Section 7/20).

## The local SOCKS-listener check (Section 21/45)

`_local_socks_listener_present` reads `/proc/net/tcp`/`/proc/net/tcp6`
(read-only) looking for a `LISTEN`-state (`0A`) entry on port 9050
(Tor's compiled-in default `SocksPort`). This never connects anywhere
(Section 44 - no `check.torproject.org`, no real SOCKS handshake).
Serein has no safe, read-only way to tie a listening socket to the Tor
process specifically - a different process could theoretically be
listening on 9050 (a false positive), and a custom, non-default
`SocksPort` (e.g. `9150`, Tor Browser's bundled port) would not be
detected by this check (a false negative) - so this is only ever
*medium-confidence, combined* evidence alongside a confirmed-active
runtime unit, never sole proof, and a custom SocksPort with no matching
listener correctly stays `usable=None`, never `True` (Section 22-23).

## torrc parsing: `%include`-aware, never an implicit `torrc.d` merge (S6R Corrective B)

`parse_tor_config()` starts from `/etc/tor/torrc` **only**.
`/etc/tor/torrc.d/` is never implicitly merged in - it is only read if
the main torrc (or something it transitively includes) contains an
explicit `%include` directive referencing it, exactly mirroring real
Tor's own config-loading behavior (a depth-limited, cycle-guarded
recursive resolver handles nested includes, both file and directory
targets). This module could not confirm from research alone whether
Ubuntu's shipped default `/etc/tor/torrc` itself contains a `%include`
line (see `docs/veil/known-limitations.md`) - the parser is correct
either way, since it only ever follows whatever `%include` state
actually exists on the host.

Directives are evaluated per their real Tor semantics, not one
identical rule for all of them:

```
SocksPort/ControlPort/TransPort/DNSPort   - multi-valued/additive: "any
                                              enabled occurrence found" -
                                              an earlier disabling "0"
                                              line never suppresses a
                                              later enabled one
CookieAuthentication                        - scalar: "last occurrence wins"
DataDirectory                                - presence-only (never used
                                                 as privacy-readiness
                                                 evidence, raw path never
                                                 exposed)
Bridge                                         - line presence only, the
                                                  matched text is never
                                                  retained or returned
```

`SocksPort`/`ControlPort`/`TransPort`/`DNSPort` are each `bool | None`:
`None` = no occurrence found anywhere reached through torrc/its
includes, `True` = at least one enabled occurrence, `False` = every
occurrence found is explicitly `0`. It never reads or stores a raw
directive value, a hashed control password, a cookie file's contents,
or a bridge line's actual text (Section 39/92). An absent directive is
never treated as "unsafe" - Tor's own compiled-in defaults matter and
are not asserted either way (Section 41).
