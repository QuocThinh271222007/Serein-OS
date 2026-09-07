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

**Explicit clear takes precedence over a stale listener (S6RM, Section
26).** `_evaluate_tor_usable()`'s own logic is unchanged by S6RM (only
the accuracy of the `socks_configured` value it receives improved) - it
still checks `socks_configured is False` *before* considering listener
evidence, so a torrc that explicitly clears `SocksPort` (e.g.
`SocksPort 9050` followed by `/SocksPort`) reports `usable=False` even
if a real listener happens to be present on port 9050 at detection time
(a stale/unrelated process, or a race with Tor's own shutdown) - this
is the exact security-relevant regression S6RM was filed to prevent
(`tests/test_veil.py::TestTorUsability::test_explicit_clear_overrides_stale_listener_evidence`).
A clear followed by a genuine re-enable (`/SocksPort` then
`+SocksPort 9050`), backed by real runtime+listener evidence, is still
legitimately `usable=True`
(`test_clear_then_reenable_with_listener_is_usable`).

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
targets, and wildcards - see below). This module could not confirm
from research alone whether Ubuntu's shipped default `/etc/tor/torrc`
itself contains a `%include` line (see `docs/veil/known-limitations.md`)
- the parser is correct either way, since it only ever follows whatever
`%include` state actually exists on the host.

## torrc is an ordered command stream, not a bag of directives (S6RM)

Live research against the Debian `torrc(5)` manual confirmed Tor's
torrc format supports three line forms, each a distinct *operation*:

```
Option value        - SET   (the plain, ordinary form)
+Option value        - APPEND (documented: "prefix the option name with
                                a plus sign, and it will be appended to
                                the previous set of options instead")
/Option                - CLEAR (documented: "prefix the option name with
                                  a forward slash" to "remove every
                                  instance of an option ... and not
                                  replace it at all")
```

`_parse_directive_line()` turns every line into `(operation, name,
value)` (`value` is `None` for `/Option`, which takes none).
`_evaluate_multi_value()` then replays every matching directive **in
file/include order** for `SocksPort`/`ControlPort`/`TransPort`/
`DNSPort` - real Tor multi-valued/additive directives (repeated plain
`Option` lines are already additive within one file per Tor's own
documented "four SocksPorts in your configuration file" example, which
is why S6R's original "any enabled occurrence found" model was already
correct for the plain-repeat case) - accumulating an entry per
`set`/`append` and **emptying the accumulated set** on every `clear`,
so a `clear` after an enabled entry produces a definite `False`, and a
later `append` after that `clear` can re-enable it:

```
SocksPort 9050                          -> True
SocksPort 9050 / SocksPort               -> False   (explicitly cleared)
SocksPort 9050 / SocksPort +SocksPort 9150 -> True  (re-enabled after clear)
SocksPort 0 +SocksPort 9050                -> True  (append still lands)
/SocksPort  (alone)                          -> False
+SocksPort 9050  (alone, nothing prior)         -> True (Tor appends to its
                                                    own non-empty compiled
                                                    default or to an empty
                                                    set either way - the
                                                    appended value alone
                                                    makes the result
                                                    non-empty, a safe,
                                                    definite answer)
(option never mentioned)                          -> None
```

`CookieAuthentication` is scalar - `set`/`append` both mean "last one
wins" (Section 12: append has no distinct multi-value meaning for a
truly scalar flag), and `/CookieAuthentication` (clear) resets to
`None` (unknown), not a guessed `False` - Serein does not want to
hardcode Tor's compiled-in default for a security-relevant scalar flag.
`DataDirectory` stays presence-only (never privacy-readiness evidence,
raw path never exposed - Section 30 explicitly allows this
simplification). `Bridge` line presence detection strips a leading
`+`/`/` before matching, so an (unusual) operator-prefixed Bridge line
is still detected as present without ever exposing its text.

`SocksPort`/`ControlPort`/`TransPort`/`DNSPort` are each `bool | None`:
`None` = the option is never mentioned anywhere reached through
torrc/its includes, `True`/`False` = the fully-ordered evaluation above.
It never reads or stores a raw directive value, a hashed control
password, a cookie file's contents, or a bridge line's actual text
(Section 23-24/39-41/92). An absent directive is never treated as
"unsafe" - Tor's own compiled-in defaults matter and are not asserted
either way (Section 41).

## `%include` wildcards (S6RM, Section 13-19)

The Debian `torrc(5)` manual documents wildcard support directly:
"This path can have wildcards. Wildcards are expanded first, then
sorted using lexical order... if the path is a file, the options... will
be parsed as if they were written where the `%include` option is. If
the path is a folder, all files [in it] will be parsed following
lexical order... The supported wildcards are `*` ... and `?`..." -
`_resolve_include()` implements exactly this: only `*`/`?` are
recognized (no other glob syntax), matches are found via `fnmatch` and
sorted lexically by filename, and each match is parsed at the
`%include` line's exact position - splicing in place, not appending at
the end (verified directly:
`tests/test_veil.py::TestTorConfigOperators::test_include_wildcard_position_preserved`
and the paired
`test_include_wildcard_lexical_order_clear_wins`/`_enable_wins` tests,
which use two files whose filenames alone decide whether the final
state is `True` or `False`). Only the *final* path segment of an
include argument is treated as a glob (Section 17/19 - the documented
and tested shape, `%include /etc/tor/torrc.d/*.conf`) - a wildcard
character earlier in the path is treated literally, a documented scope
limitation rather than a full recursive-glob implementation.

## Root confinement and traversal protection (S6RM, Section 15-16/38)

Every resolved include target - plain or wildcard - is checked with
`_is_within_root()` before it is ever read: the target is lexically
resolved (`Path.resolve(strict=False)`, which never touches the
filesystem beyond normalizing `..` segments) and rejected unless it
falls inside the injected `root`. `%include ../../../../etc/passwd`,
`%include /../../../etc/passwd`, and a wildcard variant of the same
traversal are all silently ignored (contribute zero lines) rather than
ever reading outside the injected root - confirmed by
`tests/test_veil.py::TestTorConfigOperators::test_root_escape_via_relative_traversal_is_blocked`
and its absolute/wildcard siblings, each using a sentinel secret placed
outside `root` and asserting it never appears anywhere in
`TorConfigStatus`'s output. This is the same discipline the pre-S6RM
`%include` resolver already applied to the injected-root/real-root
distinction - S6RM extends it to also cover `..`-style escapes and
wildcard-expanded matches, not just the absolute-path re-rooting case.
