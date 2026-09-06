# Container Strategy

See ADR-0011 for the full decision record. Summary:

## Chosen default: Podman + Distrobox

Both are real, verified Ubuntu 26.04 packages. Podman is rootless by
default (no persistent daemon, user-namespace UID mapping) — the
stronger default security posture for a development workstation.
Distrobox uses Podman as its backend for development sandboxes, tool
isolation, and (in S5) the Cyber Toolbox.

## Docker: documented, optional, not installed by default

Docker Engine has no Ubuntu-archive package — only Docker's own apt
repository. Serein does not add third-party apt sources by default
(Section 5's package-source policy). Docker remains available as an
explicit, user-initiated choice, and is called out specifically because
**Docker's NVIDIA Container Toolkit / GPU-passthrough support is
currently more mature than Podman's** — a real trade-off S4 (AI) may
need to weigh with concrete requirements in hand. S3 does not
pre-commit to that answer.

## Rootless-first, never automatic

Serein prefers rootless operation wherever practical (Podman's default).
If a future Docker Apply step ever required adding a user to the
`docker` group, that would need to be represented explicitly in the
plan with its own `risk`/`reason`/security consequence — never
performed silently. No such action exists in S3 (Docker is not
installed by default at all).

## Detection, never daemon interaction

`containers.py`'s detection is limited to `podman --version`/
`docker --version`/`distrobox --version` — none of which require a
running daemon for Podman (rootless, daemonless by design) or for
Docker's CLI to at least report its own version. No container is ever
created, started, or inspected during detection.

## Doctor semantics

`serein dev doctor` distinguishes "not installed" (`NOOP`/no issue) from
"both engines present" (`WARN` — a coexistence worth knowing about, not
a broken state) — never `FAIL` merely because no engine is installed on
an unprovisioned host.

## Nested-container guard

Running S3's own tooling inside a container (e.g. a CI image, or a
disposable dev container) disables the `container_engine`/`distrobox`
plan actions (`SKIP`) and capabilities (`available: false`) — a nested
container engine is unusual and often unsupported. This uses the same
shared `container_capability_available()` function for both the
capability report and the planner, avoiding the exact
capability/planner divergence S2RM had to correct for ZRAM.
