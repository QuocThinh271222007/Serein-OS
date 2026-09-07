# Isolated Cyber Toolbox Strategy

## Mechanism: Distrobox + Podman, reusing S3

`src/serein/cyber/toolbox.py`'s `detect_toolbox_status()` is a thin
wrapper over S3's `serein.development.containers.detect_container_status`
— Podman/Docker/Distrobox detection is not re-implemented. This
directly satisfies Section 5's "mechanism: Distrobox + Podman, reusing
S3's container architecture" instruction.

## Engine/Distrobox presence ≠ confirmed runtime usability

`capabilities.py`'s `container_toolbox` capability's `usable` field is
always `None`, even when Podman/Docker and Distrobox are both installed
(S5R corrective, Section 31-34): binary presence does not prove the
rootless engine's storage/network namespace actually works, or that
Distrobox can genuinely create/start a container in this environment.
Confirming that would require actually running/creating a container
(`podman run`, `distrobox create`) — exactly what S5's detection layer
must never do. `usable` stays conservative rather than overstating what
presence alone proves.

## `installed` requires the engine *and* Distrobox together

A container toolbox is "engine + Distrobox", not either component alone
(S5RM corrective, Section 2-4 — an earlier pass let a bare container
engine, with no Distrobox, report `container_toolbox.installed=true`,
which overstated what was actually present). `toolbox.py`'s
`container_toolbox_installed()` is the single helper both
`capabilities.py` and its tests use:

```python
def container_toolbox_installed(containers: CyberContainerStatusInfo) -> bool:
    engine_present = containers.podman.installed or containers.docker.installed
    return engine_present and containers.distrobox.installed
```

`container_toolbox_reason()` reports which half is actually missing
("A container engine is installed, but Distrobox is not." /
"Distrobox is installed, but no supported container engine is
detected.") rather than always claiming both are confirmed. The
planner's `toolbox.engine`/`toolbox.distrobox` actions were already
independently derived from the same two signals, so they stay
consistent with this stricter `installed` definition without any
planner change: engine-only leaves `toolbox.engine=NOOP` /
`toolbox.distrobox=APPLY`, and vice versa.

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

`mitmproxy` (toolbox — `uv`-managed Python, never system Python; see
below for why apt is deliberately *not* used despite a package
existing), Burp Suite Community (toolbox/user-managed GUI — no
automated proprietary installer or license acceptance), OWASP ZAP
(toolbox/user-managed GUI — Linux distribution mechanism verified per-
release, not assumed to be Flatpak/Snap), `ffuf`/`gobuster`/`sqlmap`
(toolbox — real, current Ubuntu 26.04 packages, preferred over an
upstream binary/git-clone install; see
`docs/cyber/tool-classification.md`), `nikto` (toolbox). None are
bundled onto the host.

## Python/Go/Rust cyber tooling: apt preferred when current, uv/toolbox otherwise

Reuses S3's `uv` ownership policy: a Python-based tool is `uv`-managed,
never `pip install`ed into system Python, specifically when its Ubuntu
package would be a meaningful step behind upstream. `mitmproxy` is the
concrete case — Ubuntu 26.04 carries `8.1.1-4` while upstream is at
`12.2.3` (live-confirmed, a 4-major-version gap), so it stays
`python-package-index`/`uv`-managed rather than apt. `pwntools`/
`impacket`/`volatility` follow the same rule. Go-sourced security tools
(`ffuf`, `gobuster`) are the opposite case: their Ubuntu 26.04 packages
are current (gobuster's apt version exactly matches upstream's latest
tag; ffuf is one minor release behind) and are therefore preferred over
a `go install`/upstream-binary install — reducing supply-chain
complexity is worth more than chasing the very latest patch release
when the two are this close (S5R Section 24/26).
