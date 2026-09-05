# Security Model

## Core principle

**The host is a trusted workstation. Risky workloads are isolated.**

Serein is not "Kali Linux plus desktop cosmetics plus CUDA." Cybersecurity
tooling, privacy tooling (Tor/Whonix-style workflows), and untrusted or
experimental software are kept out of the host package environment and run
in dedicated, isolated environments instead.

## Target architecture (future phases)

```
Serein Host  (trusted: normal dev + AI workloads live here)
│
├── normal development                (host, S3)
├── AI workloads                      (host or containerized, S4)
├── containerized security tools      (isolated, S5)
├── Kali/security VM                  (isolated, S5)
└── privacy/Whonix-style environment  (isolated, S6)
```

- The host never routes all traffic through Tor. A privacy workflow is
  something you enter, not something the whole machine becomes.
- Cybersecurity tooling is not bulk-installed onto the host "just in
  case." It is provisioned into a lab environment when a specific research
  or authorized-testing task needs it.
- Serein's own cybersecurity-related tooling is for research, education,
  defensive security, and authorized testing — not for building attack
  infrastructure against systems the operator doesn't own or have
  permission to test.

## What S0 actually enforces today

S0 has no mutation capability at all (see `installer-contract.md`), so the
isolation boundary above is a design commitment, not yet running code.
What S0 *does* enforce right now:

- Every CLI command is read-only and requires no root.
- The hardware probe never collects identifying data: no hostname, no MAC
  or IP addresses, no disk/machine serial numbers, no usernames. This
  makes `serein status` and `serein hardware probe` output safe to paste
  into a bug report without manual redaction.
- No code path shells out to `apt`, `systemctl`, or any package manager.
- No secrets, telemetry, or network calls exist anywhere in this
  repository.

## Threat model notes

- Virtualization/container detection (`hardware/environment.py`) is
  descriptive only — it tells `status`/`doctor` what context Serein is
  running in. It is not a sandbox-escape detector and must never be relied
  on as a security control.
- Profile manifests (`profile-contract.md`) are trusted local data in S0.
  When profile *sources* beyond the repository (e.g. a marketplace) are
  considered in a later phase, manifest provenance/signing must be
  designed before that door opens — not retrofitted after.

See [ADR-0004](../adr/0004-workload-isolation.md) for the reasoning behind
isolating workloads instead of bundling everything onto the host.
