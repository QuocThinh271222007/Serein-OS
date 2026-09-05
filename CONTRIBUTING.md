# Contributing to Serein OS

Serein OS is at phase **S0 — Foundation**. Read
`docs/architecture/principles.md` and `docs/roadmap.md` before proposing
anything beyond S0's scope (hardware discovery, doctor diagnostics,
profile *model*, CLI foundation) — later-phase work (desktop, AI stack,
security tooling, installer mutation) is intentionally out of scope until
its phase begins.

## Development setup

Requires Python 3.12+. `uv` is the preferred environment manager, but a
plain virtual environment works identically — nothing here depends on
`uv` at runtime.

```bash
./scripts/dev-bootstrap.sh
```

This creates a local `.venv` and installs the project in editable mode
with development dependencies (`pytest`, `jsonschema`, `ruff`, `mypy`). It
does not touch anything outside the repository checkout.

## Verifying your change

```bash
./scripts/verify.sh
```

Runs the same checks CI runs: tests, ruff, and mypy.

## Ground rules

- No system mutation in this repository until the installer contract
  (`docs/architecture/installer-contract.md`) has a real implementation
  behind it — and even then, only through
  Discover → Resolve → Plan → Validate → Apply → Verify → Record.
- No `sudo` anywhere in test or application code.
- New hardware/doctor/profile fields require a matching schema update
  (`schemas/`) and a fixture-based test (`tests/`) in the same change.
- No fake PASS output, no placeholder implementations pretending to work,
  no speculative abstractions for features that don't exist yet — see
  `docs/architecture/principles.md`.
- Runtime dependencies stay at (or near) zero. Anything beyond the
  standard library needs a specific justification in the PR description.

## Commit style

Conventional-commit-style prefixes (`feat:`, `fix:`, `docs:`, `test:`,
`chore:`) are used throughout this repository's history; please follow the
same convention.
