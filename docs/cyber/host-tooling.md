# Host Cyber Light — Baseline Tooling

## The manifest is one canonical list, not a kitchen sink

`src/serein/cyber/tools.py`'s `HOST_NETWORK_TOOLS` + `HOST_CAPTURE_TOOLS`
+ `HOST_REVERSE_ENGINEERING_TOOLS` + `HOST_FORENSICS_TOOLS` (14 tools
total) is the entire Host Cyber Light baseline. `default_apt_packages()`
returns its de-duplicated, sorted apt package list — live-validated on
Ubuntu 26.04 (`docs/validation/s5/package-validation.md`):

```
bind9-dnsutils, binutils, ethtool, file, libimage-exiftool-perl,
mtr-tiny, netcat-openbsd, nmap, openssl, socat, tcpdump, tshark,
whois, wireshark
```

This is a compact, high-value diagnostic/capture/reverse-engineering
baseline — never a full Kali-style toolset (Section 78's invariant,
enforced by `tests/test_cyber.py::TestTools::test_no_full_kali_metapackage_in_manifest`
and `TestForbiddenActions::test_no_kali_install_in_plan`).

## Network diagnostics baseline

`nmap`, `tcpdump`, `bind9-dnsutils` (dig), `whois`, `openssl`, `socat`,
`netcat-openbsd`, `mtr-tiny`, `ethtool` — ordinary diagnostic utilities,
kept deliberately separate from offensive tooling. `nmap` is
**detection-only**: `network.py` probes `nmap --version` and nothing
else; Serein never invokes `nmap` against any target, in production
code or in tests (`tests/test_cyber.py::TestNetwork::test_never_invokes_nmap_against_a_target`).

## Packet capture: `tshark`, not the `wireshark` GUI, is the host default

Live validation found installing the full `wireshark` GUI package pulls
a complete Qt6/GTK dependency stack (169 packages resolved), while
`tshark` alone resolves 48 — and `dumpcap`, the actual capture backend
both depend on, ships in the shared `wireshark-common` package that
`tshark` already pulls in. This matches Section 37's "GUI tools
optional with CLI alternatives (tshark, mitmproxy, gdb, radare2)"
guidance directly: the CLI stack (`tshark` + `dumpcap`) is what keeps
the host light and headless-capable (works over SSH/WSL with no
display), while the `wireshark` GUI package stays available/host-tier
for a user who explicitly wants it on a desktop, but is not what
`default_apt_packages()` forces onto every host by default weight.
See `docs/validation/s5/package-validation.md` Finding 2.

## Reverse engineering baseline

`file`, `binutils` (readelf/objdump/strings), `gdb`, `strace` — `gdb`
and `strace` are read directly from S3's `detect_cpp_status()` output
rather than re-probed, so there is exactly one place that owns "is gdb
installed" for the whole codebase. Heavier RE tooling (`radare2`,
`ghidra`, Cutter, Binary Ninja, IDA) is toolbox/optional/user-managed —
see `docs/cyber/reverse-engineering.md`.

## Forensics baseline

Only `exiftool` (`libimage-exiftool-perl`) is host-tier — a small,
read-only metadata-inspection utility. Heavier forensics (`sleuthkit`,
`binwalk`, `foremost`) is toolbox-tier; see
`docs/cyber/tool-classification.md`.

## What never appears in the host baseline

Password/hash cracking (`hashcat`, `john`, `hydra`, `medusa`), exploit
frameworks (`metasploit-framework`, `pwntools`), wireless auditing
(`aircrack-ng`), full web-security suites (`sqlmap`, `gobuster`,
`ffuf`, `nikto`) — all toolbox-tier by design (Section 15/77). The
doctor's `cyber_host_hygiene` check specifically WARNs (never FAILs) if
any of a small, explicit red-flag set is found already installed on the
host — see `docs/cyber/security-boundaries.md`.
