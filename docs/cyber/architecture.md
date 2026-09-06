# S5 — Cybersecurity Workspace Architecture

## Governing question

> Which cyber tools genuinely belong on the daily host, which belong in
> an isolated toolbox, which require a VM boundary, and what capability
> — network diagnostics, packet capture, reverse engineering — is
> actually available without weakening the host?

S5 answers this without installing a package, creating a container,
creating a VM, capturing a packet, or scanning a network. It follows
the same "Integrate → Measure → Replace" and "keep the daily host
clean, isolate risky tooling" principles as every earlier phase, and
the same read-only detect/plan/status/doctor shape S2-S4 established:

```
serein cyber status         read-only: what already exists
serein cyber capabilities   what Serein could safely provision, and
                             whether the underlying mechanism is usable
serein cyber plan           a deterministic, never-executed plan
serein cyber doctor         manifest/plan integrity + hygiene warnings
```

Serein is explicitly **not** Kali Linux. It does not turn the host into
a pentesting distribution, and it never automates offensive action —
see `docs/cyber/security-boundaries.md` for the hard scope boundary.

## The three-tier architecture (never collapsed)

```
Tier 1 — Host / Cyber Light
  lightweight diagnostic/network/crypto/RE tools, always on the
  daily host, no elevated privilege required to use

Tier 2 — Isolated Cyber Toolbox
  Distrobox + Podman (reuses S3's container architecture), rootless
  by default, specialized/high-volume/risky tooling lives here

Tier 3 — Full Offensive / Untrusted (VM boundary)
  KVM/QEMU/libvirt, Kali, disposable VMs, malware analysis, kernel-
  sensitive labs — Serein detects prerequisites only; VM creation is
  out of scope for S5 (a future S7/S8 concern)
```

Every tool in `src/serein/cyber/tools.py` carries exactly one
`recommended_tier` (`"host"|"toolbox"|"vm"|"user-managed"`) — see
`docs/cyber/tool-classification.md` for the model and why it is never
inferred from the tool's name.

## Module map

```
src/serein/cyber/
├── models.py          dataclasses only — CyberToolDefinition,
│                       NetworkDiagnosticsStatus, PacketCaptureStatus,
│                       ReverseEngineeringStatus, CyberContainerStatusInfo,
│                       HostHygieneStatus, VMCapabilityInfo,
│                       CyberCapability/CyberPlanAction and report wrappers
├── tools.py            the declarative, one-canonical-tier tool manifest
├── network.py          nmap/tcpdump/dig/whois/socat/nc/mtr/ethtool/
│                       openssl presence probes — never invoked against
│                       a target
├── capture.py          wireshark/tshark/dumpcap presence + capture
│                       *privilege* (dumpcap -D, read-only, never a
│                       real capture) — see packet-capture.md
├── reverse.py           file/binutils/gdb/strace (gdb/strace reused
│                       directly from S3's detect_cpp_status)/radare2/
│                       ghidra presence probes
├── toolbox.py          Podman/Docker/Distrobox status (thin wrapper
│                       over S3's detect_container_status) + host-hygiene
│                       probes (hashcat/john/msfconsole/sqlmap/aircrack-ng)
├── virtualization.py   /dev/kvm + kvm module + qemu + libvirt + a
│                       read-only os.access() user-access check — five
│                       independent signals, never one binary
├── capabilities.py     build_cyber_capabilities() — the 12-capability
│                       report
├── planner.py           build_cyber_plan() — the canonical, filterable
│                       (host/toolbox/vm) plan
├── status.py            build_cyber_status() — read-only summary
└── doctor.py             run_cyber_checks() — manifest/plan integrity,
                        host-hygiene/capture-backend/container-engine
                        WARN-not-FAIL checks
```

## Why this reuses S2/S3 rather than forking a parallel system

Per Section 59, S5 imports `CommandRunner`/`DEFAULT_RUNNER` and
`ToolStatus`/`probe_tool` from `serein.development`, `apt_package_installed`
from `serein.development.dpkg`, `detect_container_status` from
`serein.development.containers`, and `detect_cpp_status` from
`serein.development.cpp` (specifically for `gdb`/`strace`, so those two
binaries are never re-probed independently of what S3 already owns).
`detect_environment` is reused from S2's `serein.hardware.environment`
for container-nesting detection, exactly as S3 and S4 already do. No
second subprocess/package/container framework was built.

## No Apply mechanism

Exactly like S3/S4, no `serein cyber apply` command exists. Every
`CyberPlanAction` is `APPLY`/`NOOP`/`SKIP`/`BLOCKED` and nothing more —
described, never executed. No package is installed, no container or VM
is created, no packet is captured, no network is scanned, no firewall
rule or AppArmor/sysctl setting is changed by this codebase. See
`docs/cyber/security-boundaries.md` and `docs/cyber/known-limitations.md`.

## Command safety

Every detection command is read-only, timeout-bounded, and run through
the same injectable `CommandRunner` S3 established — `shell=False`
always, no interactive prompts, no target arguments. The one read-only
exception with slightly higher stakes is `dumpcap -D` (lists
capture-capable interfaces without capturing a packet) — see
`docs/cyber/packet-capture.md` for why this specific command, and only
this command, is used as capture-privilege evidence.
