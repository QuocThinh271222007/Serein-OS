# S5 — Cybersecurity Workspace Live Validation Evidence

This directory records the live Ubuntu 26.04 evidence gathered while
authoring S5's host tool manifest (`src/serein/cyber/tools.py`) and VM
planner (`src/serein/cyber/planner.py`). Tier B evidence, matching
S3/S4's own definition: real `apt`/`dpkg` package-archive access and a
real dependency-closure simulation in a disposable environment — not a
full desktop session, and (critically for S5) not real packet-capture,
KVM-nested, or wireless-hardware runtime evidence.

## Validation environment

A disposable, isolated **WSL2** instance (`Ubuntu-26.04`, installed via
`wsl.exe --install -d Ubuntu-26.04 --no-launch`), matching every prior
phase's exact methodology — **not** the developer's own running WSL
instance (`Ubuntu-24.04`, confirmed running and untouched throughout,
verified via `wsl -l -v` before and after this session's use).
Unregistered (`wsl.exe --unregister Ubuntu-26.04`) after use.

Confirmed identity:

```
PRETTY_NAME="Ubuntu 26.04 LTS"
VERSION="26.04 (Resolute Raccoon)"
VERSION_CODENAME=resolute
```

`apt-get update` ran clean against `archive.ubuntu.com`/
`security.ubuntu.com` before any package check. No third-party apt
source was configured at any point — confirmed by inspecting
`/etc/apt/sources.list.d/ubuntu.sources` (the only sources file
present) before running any package query, so every package identified
below is unambiguously Ubuntu's own.

## Files

- `package-validation.md` — the headline finding of this pass (the
  `dnsutils` transitional package no longer exists on Ubuntu 26.04 — a
  real correction, fixed in `tools.py`/`planner.py`/`capabilities.py`/
  the profile manifest) plus the full package-existence and
  dependency-closure evidence, including the `wireshark` GUI-vs-`tshark`
  CLI dependency-weight finding that shaped the host-tooling decision,
  the `qemu-system-x86_64`/`libvirt` binary-name-vs-package-name
  correction in the VM planner, and (S5R corrective) the apt-vs-upstream
  currency comparison behind `ffuf`/`gobuster`/`sqlmap`/`mitmproxy`'s
  final source decisions (Finding 5).
- `known-blockers.md` — what packet-capture, KVM-nested, and
  wireless-hardware runtime evidence remains unavailable in this
  environment and why, and what that does/doesn't mean for S5's
  correctness.

## What this validation does and does not prove

**Proves:** every Host Cyber Light candidate package (`nmap`,
`tcpdump`, `tshark`, `wireshark`, `bind9-dnsutils`, `whois`, `openssl`,
`socat`, `netcat-openbsd`, `mtr-tiny`, `ethtool`, `file`, `binutils`,
`libimage-exiftool-perl`) is a real, installable Ubuntu 26.04 package
with a clean, satisfiable combined dependency closure; `radare2`,
`sleuthkit`, `binwalk`, `hashcat`, `john`, `hydra`, `aircrack-ng`,
`sqlmap`, `gobuster`, `ffuf`, `mitmproxy`, `distrobox`, and `podman` are
all real Ubuntu 26.04 packages (toolbox-tier, none installed here);
`ghidra` and `metasploit-framework` are confirmed genuinely absent from
Ubuntu's own archive (still requiring their own official
upstream-binary/upstream-repository sources, as `tools.py` already
classified them); Ghidra's current official release (12.1.3, GitHub
Releases, `NationalSecurityAgency/ghidra`, SHA-256 checksums published)
was independently confirmed live.

**Does not prove:** anything about real packet-capture *privilege*
behavior on a genuine multi-user desktop (WSL2's default capability
model differs materially — see `known-blockers.md`), real KVM nested
virtualization, or real wireless-hardware monitor-mode capability;
that `distrobox create`/`podman pull`/any VM-creation workflow
succeeds end-to-end (deliberately never executed, in the validation
environment or anywhere else); anything about Kali's own package set
(no Kali repository was added — S5 does not target Kali as a host or
default toolbox base image).
