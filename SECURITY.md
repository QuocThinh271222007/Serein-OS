# Security Policy

## Scope

Serein OS is pre-alpha (S0 — Foundation). The current codebase is a
read-only CLI: hardware discovery, diagnostics, and profile-manifest
listing. It performs no system mutation, requires no elevated privileges,
and makes no network calls. See `docs/architecture/security-model.md` for
the full security model and `docs/architecture/installer-contract.md` for
the (unimplemented) mutation contract future phases must follow.

## Reporting a vulnerability

Please open a GitHub issue on this repository describing the concern. If
the issue involves a way to trigger unintended mutation, privilege
escalation, or credential/secret exposure, note that explicitly in the
report title so it can be triaged quickly. Do not include exploit code
targeting third-party systems.

## Intended use

Any cybersecurity-related tooling this project adds in later phases (see
`docs/roadmap.md`, S5) is intended for research, education, defensive
security, and authorized testing only, within isolated environments per
[ADR-0004](docs/adr/0004-workload-isolation.md).
