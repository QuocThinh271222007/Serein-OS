# ADR-0009: Python Environment Management (uv, system Python untouched)

## Status

Accepted

## Context

Ubuntu owns `/usr/bin/python3` and its `dist-packages`; nothing in this
project may treat it as a place to install project dependencies (`sudo
pip install ...` corrupts the system's own package manager's view of
what's installed, a well-documented and easily-triggered failure mode).
S3 needs one clear, current, low-risk mechanism for *project-level*
Python environments and tool execution.

## Decision

- **System Python stays exactly as Ubuntu ships it.** Serein never
  writes to it, never changes `/usr/bin/python3`'s symlink target, and
  never runs `pip install` against it (with or without `sudo`).
- **`uv`** (Astral) is Serein's preferred tool for project environments,
  dependency sync, Python-version management for projects, and running
  CLI Python tools (`uv tool`/`uvx`). No Ubuntu package exists for `uv`
  on any current release; the official, upstream-recommended
  installation method is `astral.sh/uv/install.sh`, a user-level
  installer with no `sudo` step. Serein documents this as the plan
  action's `verification`/`reason` text — it is never executed by S3.
- **Existing user tooling (`pyenv`, Conda, `micromamba`) is detected and
  reported, never removed or replaced.** A user who already manages
  Python their own way keeps doing so; `uv` is offered for new projects,
  not forced onto existing ones.
- **Micromamba is optional**, offered only for projects that specifically
  need the Conda package ecosystem — not installed by default (S4's
  AI-specific Conda needs, if any, are out of S3's scope).

## Consequences

- Every Serein-managed Python workflow is additive: nothing a developer
  already has (a pyenv install, a Conda environment) is disturbed.
- `uv`'s absence of an Ubuntu package means its installation always
  requires a documented, one-time script run outside Serein's own
  execution — consistent with every other S3 language-bootstrap tool
  (rustup, fnm), not a special case.
- If Ubuntu ever ships a current, well-maintained `uv` package, this
  ADR should be revisited (Integrate → Measure → Replace favors the
  simpler source once one exists).

## Alternatives considered

**pipx as the primary tool.** Rejected as primary: pipx solves CLI-tool
isolation well but does not replace `uv`'s project-environment/dependency-
sync/Python-version-management role, which is the more common day-to-day
need for the kind of project development this ADR targets.

**Poetry.** Rejected: uv is presently faster, has significant upstream
momentum, and additionally covers Python-version management (a
capability Poetry defers to a separate tool), reducing the number of
distinct tools S3 needs to reason about.
