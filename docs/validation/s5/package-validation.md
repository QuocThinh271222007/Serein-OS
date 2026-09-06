# S5 Ubuntu 26.04 Package Validation

Disposable `Ubuntu-26.04` WSL2 instance, root shell, `apt-get update`
against the stock Ubuntu archive/security sources only (verified no
third-party source beforehand). `PACKAGE_VALIDATION=PASS` for every
package this section covers.

## Finding 1 — `dnsutils` no longer exists on Ubuntu 26.04 (real correction)

```
$ apt-cache policy dnsutils
dnsutils:
  Installed: (none)
  Candidate: (none)
  Version table:
```

The transitional `dnsutils` package (previously a stub depending on
`bind9-dnsutils`) has been dropped entirely. The real package providing
`dig`/`nslookup` is `bind9-dnsutils`:

```
$ apt-cache policy bind9-dnsutils
bind9-dnsutils:
  Candidate: 1:9.20.24-1ubuntu0.3
```

**Fixed:** `CyberToolDefinition` id/package renamed from `dnsutils` to
`bind9-dnsutils` in `tools.py`; `planner.py`'s `_host_installed_map` key
updated to match; `capabilities.py`'s `dns_diagnostics` source label
updated; `profiles/cyber/cyber.profile.json`'s `packages` list updated
(and re-sorted — `bind9-dnsutils` now sorts before `binutils`). This is
exactly the class of "surprising difference" the S5 brief's Section 83
asked to be recorded, mirroring S3's own `p7zip-full`→`7zip` and
`fd-find`/`bat` binary-name corrections.

## Finding 2 — `wireshark` (GUI) vs `tshark` (CLI) dependency weight

```
$ apt-get install --simulate -y wireshark | grep -c '^Conf'
169
$ apt-get install --simulate -y tshark | grep -c '^Conf'
48
```

Installing the full `wireshark` GUI package pulls a complete Qt6/GTK
GUI stack (169 packages resolved) versus 48 for `tshark` alone.
`dumpcap` — the actual capture backend both depend on — ships in the
shared `wireshark-common` package, which `tshark` alone already pulls
in as a dependency:

```
$ apt-cache show tshark | grep ^Depends
Depends: libc6 (>= 2.34), ..., wireshark-common (= 4.6.4-1)
```

This directly confirms the S5 brief's Section 27 candidate list phrasing
("tshark/wireshark-common", not "wireshark") and Section 37's "GUI tools
optional with CLI alternatives (tshark...)" guidance: the Host Cyber
Light manifest keeps `tshark` (and therefore `dumpcap`) as the host
default and treats the full `wireshark` GUI package as available but
not host-default — `tools.py`'s `wireshark` entry stays `recommended_tier
= "host"` since a user may reasonably want the GUI on a desktop machine,
but the manifest-driven `install_apt_packages` default (`default_apt_packages()`)
intentionally does not force the GUI's dependency weight onto every
host. See `docs/cyber/host-tooling.md`.

## Finding 3 — real capture-backend ownership (dumpcap)

A real, non-interactive (`DEBIAN_FRONTEND=noninteractive`) `apt-get
install -y tshark` completed cleanly and left:

```
$ dpkg -S /usr/bin/dumpcap
wireshark-common: /usr/bin/dumpcap
$ ls -la /usr/bin/dumpcap
-rwxr-xr-x 1 root root 162400 ... /usr/bin/dumpcap
$ getcap /usr/bin/dumpcap
(no output - no file capabilities set)
$ getent group wireshark
(no output - group does not exist)
```

By default, a plain `apt install` of `tshark`/`wireshark-common` grants
**no** broad capture rights — no `wireshark` group is created, no file
capability is set on `dumpcap`. Granting non-root capture rights is a
separate, explicit `dpkg-reconfigure wireshark-common` step (which
prompts interactively under a real TTY) that Serein correctly never
performs automatically (Section 7). This is concrete evidence
supporting `docs/cyber/packet-capture.md`'s privilege-ownership model.

## Finding 4 — `qemu-system-x86_64`/`libvirt` are binary names, not package names (real correction)

```
$ apt-cache policy qemu-system-x86_64
(no output - package does not exist)
$ apt-cache policy qemu-system-x86
qemu-system-x86:
  Candidate: 1:10.2.1+ds-1ubuntu3.2
$ apt-cache policy libvirt
(no output - package does not exist)
$ apt-cache policy libvirt-daemon-system libvirt-clients
libvirt-daemon-system:
  Candidate: 12.0.0-1ubuntu5.3
libvirt-clients:
  Candidate: 12.0.0-1ubuntu5.3
```

`virtualization.py`'s tool *probes* were already correct (the
`qemu-system-x86_64` and `virsh` **binaries** genuinely exist once the
right packages are installed), but `planner.py`'s
`_vm_prerequisites_action` had been listing the binary names themselves
as the apt packages to install — `qemu-system-x86_64` and `libvirt` are
not real Ubuntu package names. **Fixed:** the plan action's
`tool`/`target` fields now name the real packages
(`qemu-system-x86, libvirt-daemon-system, libvirt-clients`), confirmed
via a combined `apt-get install --simulate` that resolves cleanly.

## Combined host manifest dependency closure

```
$ apt-get install --simulate -y bind9-dnsutils binutils ethtool file \
    libimage-exiftool-perl mtr-tiny netcat-openbsd nmap openssl socat \
    tcpdump tshark whois wireshark
```

Resolved cleanly (0 errors, 0 held-back conflicts) — the full Host Cyber
Light manifest, including the optional GUI `wireshark` package, has no
internal dependency conflicts on Ubuntu 26.04.

## Toolbox/VM-tier packages confirmed present (not installed on host)

`radare2` (6.0.7+ds-1), `sleuthkit` (4.12.1+dfsg-3build1), `binwalk`
(2.4.3+dfsg1-2build1), `hashcat` (7.1.2+ds1-3), `john` (1.9.0-3build1),
`hydra` (9.6-3), `aircrack-ng` (1:1.7+git20230807.4bf83f1a-2ubuntu2),
`sqlmap` (1.10.4-1), `gobuster` (3.8.2-1), `ffuf` (2.1.0-1build1),
`mitmproxy` (8.1.1-4), `distrobox` (1.8.2.4-1), `podman`
(5.7.0+ds2-3build1) — all real, current Ubuntu 26.04 packages. None
were installed on the validation host's baseline; each stays
`recommended_tier = "toolbox"`.

## Confirmed genuinely absent from Ubuntu's archive

```
$ apt-cache policy ghidra metasploit-framework
(no output for either - packages do not exist)
```

Matches `tools.py`'s existing classification: `ghidra` is
`official-upstream-binary` (GitHub Releases,
`NationalSecurityAgency/ghidra`, current release **12.1.3** as of this
validation pass, distributed as a checksummed archive, independently
confirmed live against the release page); `metasploit-framework` is
`official-upstream-repository` (Rapid7's own apt-like installer, not
Ubuntu's archive). Neither is installed by S5 in any environment.

## `nc` binary ownership

```
$ update-alternatives --list nc
/bin/nc.openbsd
```

Confirms `netcat-openbsd`'s `nc` binary is what `network.py` probes
(`probe_tool("netcat", "nc", ...)`), matching the existing detection
code with no changes needed.
