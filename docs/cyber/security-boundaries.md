# Security Boundaries

S5 is OS integration, not attack automation. This document is the
single place that lists everything the cyber subsystem must never do —
every item here is enforced by a specific regression test, not prose
alone.

## Never built

Automated exploitation chains, credential spraying, password-cracking
orchestration, persistence tooling, malware deployment, C2
infrastructure, phishing automation, mass scanning, or target discovery
against public networks. `serein cyber` may detect, classify, plan
(never execute), report permissions, and — in a future phase — launch
an isolated workspace; it never automates an offensive action itself.

## No Apply engine (Section 4)

No `serein cyber apply` exists. No package is installed, no container
or VM is created, no firewall rule is mutated, no network scan runs, no
packet is captured by any code path in this codebase.

## No active network probing

No port scan, ping sweep, DNS enumeration, HTTP probing, ARP scan, or
broadcast discovery is ever performed. `nmap`'s only invocation is
`nmap --version`
(`tests/test_cyber.py::TestNetwork::test_never_invokes_nmap_against_a_target`).
The planner's `verification` fields are version-check-shaped strings
only (`nmap --version`, not `scan localhost`) — enforced by
`TestForbiddenActions::test_verification_fields_are_version_checks_only`
and `test_no_active_scan_commands_in_plan` (scans every action for
`nmap <target>`/`masscan`/`arp-scan`/`tcpdump -i`/`tshark -i`-shaped
text).

## No privileged container defaults

The default toolbox plan never requires `--privileged=true`, host
networking, or `CAP_SYS_ADMIN` — enforced by
`TestForbiddenActions::test_no_privileged_container_defaults`. If a
future toolbox category genuinely needs elevated container privileges,
the correct model is `BLOCKED` pending explicit future authorization.

## No host mutation

S5 does not alter `ufw`/`nftables`/`iptables`/firewalld state, does not
enable an SSH server, does not disable AppArmor, and does not modify
`ptrace_scope`/`ip_forward`/`rp_filter`/unprivileged-userns or any other
kernel-hardening sysctl — it may *report* a requirement, never modify
one. Host mutation counters (`S5_SUDO_COMMAND_COUNT`,
`S5_PACKAGE_INSTALL_COUNT`, `S5_CONTAINER_CREATE_COUNT`,
`S5_VM_CREATE_COUNT`, `S5_PACKET_CAPTURE_COUNT`,
`S5_NETWORK_SCAN_COUNT`, `S5_FIREWALL_MUTATION_COUNT`,
`S5_CAPABILITY_MUTATION_COUNT`, `S5_USER_CONFIG_WRITE_COUNT`) are all
`0` for this codebase.

## No unsafe privilege recommendations

Serein never recommends `chmod 777`, passwordless sudo, a world-
writable capture device, Docker-socket exposure, root-shell
persistence, or disabling the firewall/AppArmor/Secure Boot.

## Privacy

Status/doctor never inspect browser history, saved scan targets, SSH
`known_hosts`, VPN profiles, Wi-Fi credentials, packet captures, or
Burp projects — there is no user-target inventory anywhere in this
codebase. Default JSON/status output avoids exposing MAC addresses, VPN
peer identities, Wi-Fi SSIDs, or a public IP; captured interface names
from `dumpcap -D` specifically are never surfaced (see
`docs/cyber/packet-capture.md`). `tests/test_cyber.py::TestPrivacy`
scans real status/plan/capabilities JSON output for hostname/username/
interface-name/temp-path leakage.

## Malware analysis: never host, never an ordinary toolbox

An untrusted or suspected-malicious binary requires a disposable VM.
Container isolation, including the isolated Distrobox/Podman toolbox,
is explicitly documented as insufficient for hostile kernel/userspace
samples — see `docs/cyber/vm-isolation.md`.
