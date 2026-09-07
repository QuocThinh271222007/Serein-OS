"""DNS leak model - a dedicated state, never inferred from Tor alone.

"Tor is active" does not imply "DNS is safe" (Section 12): a SOCKS4 or
plain-SOCKS application configuration resolves hostnames locally
(leaking them to the host/ISP resolver) even while its actual traffic
routes through Tor. Serein's recommended route is SOCKS5h (the proxy
itself resolves hostnames) or Tor Browser, which handles this
correctly by design (Section 11/64) - never host DNS plus a bare SOCKS
proxy for an application that supports SOCKS5h.

This module never mutates ``/etc/resolv.conf``, system DNS, or any
resolver configuration (Section 3/102) - ``system_dns_unchanged`` is a
policy constant, not a probe result.
"""

from __future__ import annotations

from serein.veil.models import DnsPrivacyStatus, TorStatusInfo


def evaluate_dns_privacy(tor: TorStatusInfo) -> DnsPrivacyStatus:
    if tor.usable is not True:
        return DnsPrivacyStatus(
            dns_isolation_proven=None, confidence="low",
            reason="Tor client usability is not confirmed, so DNS routing "
            "through Tor cannot be evaluated either. No DNS isolation is "
            "claimed.",
        )
    return DnsPrivacyStatus(
        dns_isolation_proven=None, confidence="low",
        reason="Tor client is usable, but Serein does not verify any "
        "specific application's DNS behavior - 'Tor active' never implies "
        "'DNS safe' (Section 12). Use SOCKS5h (proxy-resolved hostnames) "
        "or Tor Browser, never host DNS plus a bare SOCKS proxy, for any "
        "application that must not leak hostname lookups.",
    )
