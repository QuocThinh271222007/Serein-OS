# System Overview

## What exists today (S0)

```
serein (CLI, src/serein/)
├── core/       status aggregation (serein status)
├── doctor/     foundation diagnostics (serein doctor)
├── hardware/   read-only hardware discovery (serein hardware probe)
└── profiles/   profile manifest model + registry (serein profile list)
```

The CLI is the only executable surface. It talks to `/proc`, `/sys`, and
`/etc/os-release` directly (no root, no external services) and to the
`profiles/` and `schemas/` directories shipped in the repository.

```
                     ┌─────────────┐
   user ── serein ──▶│     CLI     │
                     └──────┬──────┘
                            │
        ┌─────────┬────────┼────────┬──────────┐
        ▼         ▼         ▼        ▼          ▼
     version   status    doctor   hardware   profile
                  │         │      probe       list
                  └────┬────┴────┬───┘          │
                       ▼         ▼               ▼
                 hardware.probe()          profiles/registry.py
                       │                          │
              /proc, /sys, /etc/os-release   profiles/*/*.profile.json
```

## What does not exist yet

- Any code path that writes to the filesystem outside of the repository
  checkout, calls `apt`, touches `systemd`, or requires root.
- Profile *activation* (switching the active profile). `profile list` only
  enumerates declared/implemented manifests.
- A desktop environment, AI stack, security tooling, or privacy layer —
  see `docs/roadmap.md` for where each lands.

## Why this shape

- **`hardware/` is pure and injectable.** Every probe function takes a
  `root: Path` standing in for `/`, so detection logic is unit-testable
  against fixture directory trees without touching the real host or
  requiring Linux to run the test suite. See `hardware-contract.md`.
- **`doctor/` and `core/status.py` are thin consumers of `hardware/`.**
  Neither re-implements probing; they interpret its output.
- **`profiles/` is data-driven.** A profile is a JSON document validated
  against `schemas/profile.schema.json`, not a Python function — so a
  future mutating "apply" implementation can consume the exact same
  manifests S0 defines.
