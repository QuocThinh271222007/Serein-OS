# ADR-0011: Development Container Engine (Podman default, Docker optional)

## Status

Accepted

## Context

Serein needs one primary container engine for development workflows,
with an architecture that does not foreclose Docker where its ecosystem
is genuinely ahead — specifically NVIDIA Container Toolkit / GPU-passthrough
maturity, which S4 (AI) will need. Installing both engines' daemons by
default risks the well-known "two container runtimes fighting over the
same resources/sockets" failure mode this project has avoided elsewhere
(S2's power-manager and ZRAM-implementation conflict-avoidance rules).

## Decision

- **Podman** is the default, installed container engine
  (`podman` — a real Ubuntu 26.04 package, verified). Rootless by
  default, no daemon required, pairs directly with Distrobox.
- **Distrobox** (also a real Ubuntu package) is installed alongside
  Podman for development sandboxes, tool isolation, and (later) S5's
  Cyber Toolbox — using Podman as its backend.
- **Docker is not installed by default.** It has no Ubuntu-archive
  package — only Docker's own apt repository, which Serein does not add
  automatically (avoiding an unrequested third-party apt source, per
  Section 5's package-source policy). Docker is documented as
  `optional`, for the specific, deferred case where S4's AI-container
  ecosystem needs Docker's more mature NVIDIA Container Toolkit
  integration — a decision that phase will make with real evidence, not
  one S3 pre-commits to.
- If **both** engines are ever detected on a host (a user's own prior
  choice), the planner reports `NOOP` and does not attempt to remove or
  prefer one — `serein dev doctor` reports it as a `WARN` (coexistence
  worth knowing about, not a broken state).

## Consequences

- A Serein-provisioned workstation has exactly one container daemon
  surface by default (Podman's rootless model has no persistent daemon
  at all), minimizing conflict risk out of the box.
- S4's GPU-container work may still choose Docker if warranted — this
  ADR does not block that, it only refuses to guess the answer now
  without S4's actual requirements in hand.
- Users who already run Docker (e.g. via Docker Desktop's WSL
  integration) are never fought — detected, reported, left alone.

## Alternatives considered

**Docker as the default.** Rejected: no Ubuntu-archive package (would
require adding Docker's own apt repo by default, a bigger default
footprint than Podman needs), and rootless Docker requires materially
more manual setup than Podman's rootless-by-default model.

**Installing both by default.** Rejected: doubles the conflict surface
(sockets, cgroup delegation, potential confusion about which `docker`/
`podman` command a script picks up) for no benefit S3 can currently
justify with evidence.
