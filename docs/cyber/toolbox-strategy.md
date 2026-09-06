# Isolated Cyber Toolbox Strategy

## Mechanism: Distrobox + Podman, reusing S3

`src/serein/cyber/toolbox.py`'s `detect_toolbox_status()` is a thin
wrapper over S3's `serein.development.containers.detect_container_status`
— Podman/Docker/Distrobox detection is not re-implemented. This
directly satisfies Section 5's "mechanism: Distrobox + Podman, reusing
S3's container architecture" instruction.

## Rootless by default; no privileged defaults, ever

`planner.py`'s `_toolbox_engine_action` plans Podman as the default
engine and explicitly documents "never `--privileged`, never
`--network=host` by default" in its reason field. This is enforced as a
real regression (`tests/test_cyber.py::TestForbiddenActions::test_no_privileged_container_defaults`
scans every toolbox-component action's command-shaped fields for
`--privileged`, `--network=host`, `CAP_SYS_ADMIN`, and `/dev/` device
paths). If a future toolbox category genuinely needs raw sockets, host
networking, USB, or a wireless interface, the correct representation is
`BLOCKED` pending explicit future user authorization — never a silent
default privilege expansion (Section 32).

Serein also does not assume a rootless container can do everything a
network-security task might need: packet capture on the *host* NIC,
wireless monitor mode, and raw packet injection may genuinely require
host or VM-level access that a rootless container cannot provide
(Section 33) — this is a real capability gap `toolbox-strategy.md`
records rather than papers over.

## Base image: Ubuntu/Debian-based, not Kali, by default

`_toolbox_distrobox_action`'s reason field is explicit: "General cyber
toolbox target is Ubuntu/Debian-based via Distrobox — not a Kali
container by default." A Kali Distrobox/Podman toolbox may be
documented later as an optional, explicitly-chosen configuration — not
the universal default — because of Kali's large rolling-release
toolset, dependency churn, and the network-/privilege-heavy tooling
many of its packages assume (Section 30).

## Declarative categories, not an installed image

S5 defines toolbox tool categories (`TOOLBOX_RECON_TOOLS`,
`TOOLBOX_WEB_TOOLS`, `TOOLBOX_PASSWORD_AUDIT_TOOLS`,
`TOOLBOX_EXPLOIT_DEV_TOOLS`, `TOOLBOX_WIRELESS_TOOLS`,
`TOOLBOX_FORENSICS_TOOLS`, `TOOLBOX_REVERSE_ENGINEERING_TOOLS`) in
`tools.py` — a classification, not a provisioned environment. No
`podman pull`, no `distrobox create`, and no container image is ever
built or fetched by S5 (Section 65). See
`docs/cyber/tool-classification.md` for the full per-tool source
strategy.

## Web-security tooling is individually classified, not bulk-included

`mitmproxy` (toolbox/optional host — CLI-friendly, `uv`-managed Python,
never system Python), Burp Suite Community (toolbox/user-managed GUI —
no automated proprietary installer or license acceptance), OWASP ZAP
(toolbox/user-managed GUI — Linux distribution mechanism verified per-
release, not assumed to be Flatpak/Snap), `ffuf`/`gobuster` (toolbox,
small Go binaries), `nikto`/`sqlmap` (toolbox). None are bundled onto
the host.

## Python/Go/Rust cyber tooling never targets system Python

Reuses S3's `uv` ownership policy exactly: `pwntools`, `impacket`,
`mitmproxy`, `volatility` are `uv`-managed or toolbox-installed, never
`pip install`ed into system Python. `go install`/`cargo install`
security tools default to the toolbox unless a specific tool is small
and justified enough to be host-tier (none currently are).
