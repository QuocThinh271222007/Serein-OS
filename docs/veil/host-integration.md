# Host Integration Limits

## What S6 never touches

Explicitly forbidden, and never done anywhere in `src/serein/veil/`
(each backed by a regression in `tests/test_veil.py::TestInvariants`/
`TestNoExternalNetworkOrLeaks`):

- `/etc/resolv.conf`, system DNS, or any resolver configuration.
- The default route, or any `NetworkManager` global proxy setting.
- Firewall rules (`nftables`/`iptables`/`ufw`/`firewalld`).
- System-wide proxy environment variables (`HTTP_PROXY`/`HTTPS_PROXY`/
  `ALL_PROXY`) - a future Veil launcher may set *scoped*, per-process
  environment variables for a specific workspace process; S6 does not
  implement that launcher.
- A system-wide transparent Tor proxy (`TransPort`/`DNSPort`/
  `iptables`/`nft` redirect) - documented as a possible future advanced
  mode, never the default (`docs/veil/dns-leak-model.md`).
- Any existing browser's settings - Tor Browser and a future isolated
  profile are both separate from, and never mutate, an ordinary browser
  profile.
- The host clock, locale, or NTP configuration - Whonix/Tor Browser own
  their own privacy-relevant behavior here; Serein does not recreate
  fingerprint defenses at the OS level (Section 74-75).

## Clipboard and shared folders (Section 35-36)

Clipboard sharing and shared folders are both potential metadata/
content leak vectors for a privacy VM or workspace. Serein does not
globally disable clipboard access - only documents that a future
Whonix/private profile should default clipboard integration and shared
folders to off/minimal, with explicit opt-in required, never a mounted
home directory.

## Downloads stay inside the boundary (Section 80-82)

Documented future policy, not yet implemented: downloads made inside a
private workspace/Tor Browser session should remain inside that
boundary by default, requiring an explicit export step rather than
auto-opening on the host (which can deanonymize a workflow by handing a
file to an ordinary, non-isolated application).

## Filesystem privacy (Section 78-79)

A future private workspace's storage should be either genuinely
ephemeral or an explicit, clearly separate persistent store - never
silently mixed with the host's ordinary home directory. `storage
_persistence = ephemeral | persistent | unknown` is documented here as
a future model field; S6 creates no storage of any kind.

## WSL limitations (Section 83)

A WSL environment may support a Tor client, a SOCKS proxy, and some
browser/process-level testing, but it cannot prove the same isolation
model as a full Linux host with real KVM/libvirt - Whonix/KVM is
typically unavailable there (`whonix.py`'s VM-readiness check correctly
reports `blocked_no_hardware` in that case, never a false "ready").
Serein never claims WSL parity with a bare-metal or full-VM host for
Whonix-tier isolation.

## Headless operation (Section 84)

`serein veil status`/`doctor` work correctly with no browser, no Tor
daemon, and no KVM present - every optional capability degrades to
`None`/`SKIP`, never an error.
