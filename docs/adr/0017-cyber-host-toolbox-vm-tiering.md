# ADR-0017: Cybersecurity Tool Tiering (Host / Toolbox / VM)

## Status

Accepted

## Context

Serein needs to answer, for every cyber-relevant tool, where it belongs
without turning the daily host into a pentesting distribution. Every
prior phase (S2 hardware, S3 development, S4 AI) established that
"detect capability, plan conservatively, never mutate the host by
surprise" is the right posture; S5 extends the same discipline to a
domain where the tools themselves range from harmless (`dig`) to
genuinely dangerous if misused (`hashcat`, Metasploit, wireless
injection tooling). A single flat tool list with no tiering would force
either "install everything on the host" (rejected outright — Serein is
not Kali) or "install nothing" (useless — network/RE diagnostics are
legitimately host-appropriate).

## Decision

Three tiers, one canonical `recommended_tier` field per tool
(`CyberToolDefinition` in `src/serein/cyber/tools.py`):

- **Host / Cyber Light** — lightweight, always-safe-to-have diagnostic/
  capture/RE tooling (`nmap`, `tcpdump`, `tshark`, `dig`, `whois`,
  `openssl`, `file`, `binutils`, `gdb`, `strace`, ...). No elevated
  privilege is required merely to have these installed.
- **Isolated Cyber Toolbox** — specialized, high-volume, dependency-
  heavy, conflicting, or risky tooling (`hashcat`, `john`, `hydra`,
  Metasploit, `radare2`, `ghidra`, `sqlmap`, `aircrack-ng`, ...),
  reached via Distrobox/Podman (ADR-0018).
- **VM / Full Isolation** — Kali, untrusted binaries, kernel-sensitive
  labs, full offensive environments (ADR-0020).

`planner.py` and `capabilities.py` both filter by this single field —
neither maintains a second, independently-drifting classification.
Risk (`none`/`low`/`medium`/`high`) is a separate field describing
install/host impact, never inferred from the tier or the tool's name
alone (Section 62).

## Consequences

- A user asking "what does Serein consider host-safe" gets one
  authoritative, testable answer (`serein cyber status`/`capabilities`),
  not prose scattered across multiple modules.
- Adding a new tool later requires exactly one classification decision,
  not a decision plus a search for every other place a similar list
  might need updating.
- The host package manifest (`docs/cyber/host-tooling.md`) stays
  provably compact — a doctor check (`cyber_package_manifest`) fails
  loudly if a tool's tier value is ever invalid, and a dedicated test
  (`TestForbiddenActions::test_no_kali_install_in_plan`) fails if a
  full Kali metapackage is ever added at host tier.

## Alternatives considered

**Two tiers (host vs. everything-else).** Rejected: collapses the
meaningful difference between "needs an isolated but ordinary rootless
container" and "needs a hardware-level VM boundary because the workload
is actively hostile" — exactly the distinction that matters most for
malware analysis and Kali (ADR-0020).

**Per-category tier lists instead of a per-tool field.** Rejected:
would require every category (network, RE, forensics, ...) to
independently repeat the host/toolbox/vm split, inviting drift; a
single per-tool field is the smaller, more auditable surface.
