# Profile Manifest Contract

## Purpose

A profile is a declarative description of a Serein capability bundle —
packages, services, configuration units, hardware preconditions, and
verification checks — validated against `schemas/profile.schema.json`.
Profiles exist so that future mutating behavior consumes structured data
instead of ad hoc shell scripts scattered across the repository.

## Three distinct states

Every profile-related surface (`serein profile list`, `ProfileEntry`) must
distinguish:

| State         | Meaning                                                              |
|---------------|-----------------------------------------------------------------------|
| `declared`    | The identity is named in the roadmap; no manifest exists yet.        |
| `implemented` | A manifest exists and validates, but may still apply nothing (S0).   |
| `active`      | The profile is the one currently applied to this host.               |

**S0 never reports `active=true` for anything** — activation (the code
path that would actually apply a profile) is not implemented. Reporting an
inactive profile as active would violate the "no fake PASS output" rule
that also governs `doctor`.

## S0 scope

- `core` is the only `implemented` profile: `profiles/core/core.profile.json`.
  It describes the unmodified host — empty `packages`/`services`/etc. — and
  exists to prove the schema and loader work end to end, not to do
  anything yet.
- `balanced`, `dev`, `ai`, `battery`, `cyber` are `declared` only
  (`src/serein/profiles/registry.py:DECLARED_ONLY_PROFILES`). They carry a
  name and description so the roadmap is visible in `profile list`, and
  nothing else.
- `desktop`/veil-privacy profiles are **not** declared yet; they belong to
  S1/S6 respectively and should be added when those phases start, not
  before.

## Manifest fields

See `schemas/profile.schema.json` for the authoritative shape. Fields such
as `packages`, `services`, `configuration_units`, `hardware_conditions`,
and `verification_checks` are contract surface for the installer
(`installer-contract.md`) to consume later; an empty array is a valid,
honest value for a profile that does nothing yet — it is not a placeholder
that silently gets treated as "not applicable."

## Loading

`profiles/registry.py:list_profiles()` reads every
`profiles/*/*.profile.json` file it can parse, falling back silently (not
crashing) on an unreadable or malformed manifest — a broken third-party
profile must never take down `profile list`. Manifest-backed entries take
precedence over a same-`id` declared-only stub.
