# DNS Leak Model

## "Tor active" does not mean "DNS safe" (Section 12)

A SOCKS4 (or plain-SOCKS) application configuration resolves hostnames
*locally* before handing the connection to the proxy - the hostname
lookup itself leaks to the host/ISP resolver even while the actual
traffic routes through Tor afterward. `src/serein/veil/dns.py`'s
`evaluate_dns_privacy()` never infers `dns_isolation_proven` from
`tor.usable` alone - it is `None` in every case S6 can currently
produce, whether Tor is usable, not usable, or unknown:

```python
if tor.usable is not True:
    return DnsPrivacyStatus(dns_isolation_proven=None, ...)
# tor.usable is True:
return DnsPrivacyStatus(dns_isolation_proven=None, ...)  # still None
```

Proving real per-application DNS isolation would require verifying that
specific application's actual resolver behavior at runtime - out of
scope for a read-only detection layer with no Apply mechanism.

## Recommended route (Section 11/64)

```
application -> SOCKS5h -> Tor
```

`SOCKS5h` specifically means the *proxy* resolves the hostname, not the
local system - this is the critical distinction from plain `SOCKS5`/
`SOCKS4`. Serein's `resolver_strategy` field is a constant policy
value (`"socks5h_or_tor_browser"`), not a per-host probe result: it
documents what Serein recommends, not what it detected. Tor Browser
handles this correctly by design and is the preferred route for web
browsing specifically (see `docs/veil/tor-browser.md`) - "host DNS +
bare SOCKS" is never recommended for an application that supports
SOCKS5h.

## Never mutated (Section 3/102)

`system_dns_unchanged` is always `True` - a policy constant, not a
probe result. Serein never touches `/etc/resolv.conf`, system DNS
configuration, `NetworkManager`'s global settings, or any resolver
configuration in S6. This is enforced as a direct regression
(`tests/test_veil.py::TestInvariants::test_default_plan_never_replaces_global_dns`)
scanning every plan action's text fields for `resolv.conf`.

## Transparent DNS proxying is not the default (Section 10)

Detecting a `DNSPort`/`TransPort` directive in `torrc` (see
`docs/veil/tor-strategy.md`) is purely informational - Serein never
proposes enabling transparent DNS/traffic redirection as a plan action.
The complexity/leak surface (application exceptions, UDP behavior,
root/network mutation, a hard-to-prove kill switch - Section 10) is
explicitly why this stays documented-only, reserved as a possible
future advanced mode, never the default mechanism.
