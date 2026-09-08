# Serein Distribution (S7.0)

Assembles a private, internal "Serein OS Alpha" ISO by remastering a
verified upstream Ubuntu release image with a controlled Serein payload
overlay. See [`docs/distribution/architecture.md`](../docs/distribution/architecture.md)
for the full design and [`docs/distribution/known-limitations.md`](../docs/distribution/known-limitations.md)
for exactly what this phase does and does not implement.

**Not a public release.** The project has no selected license yet - see
[`docs/distribution/licensing-and-release-boundary.md`](../docs/distribution/licensing-and-release-boundary.md).

## Layout

```
distribution/
├── base-image.json     pinned upstream Ubuntu image provenance (contract)
├── build-config.json    build tooling/volume-id/filename-template config
├── overlay/              static files applied onto the extracted ISO tree
├── boot/                  QA-only boot-entry templates, never the production default
├── scripts/                thin bash entrypoints (see below)
└── test-fixtures/           small fixture trees used by tests/test_distribution.py
```

The actual build logic lives in `src/serein/distribution/` (Python), not
in these scripts - see Section 77 of the S7.0 contract. Nothing under
`distribution/` is ever mutated by a build; a build writes into
`build/work/` (git-ignored) and `dist/` (git-ignored) only.

## Operations (each is explicit - never run implicitly by pytest/CI)

```bash
./distribution/scripts/fetch-base-image.sh     # downloads the pinned Ubuntu ISO (~6 GB)
./distribution/scripts/verify-base-image.sh     # sha256 (+ optional GPG) verification, fail-closed
./distribution/scripts/build-iso.sh              # the one canonical build entrypoint
./distribution/scripts/inspect-iso.sh <path>      # read-only structural inspection
./distribution/scripts/boot-smoke.sh <iso>         # bounded QEMU boot validation (requires qemu)
./distribution/scripts/clean.sh [--all]             # safe cleanup of build/ (and optionally the cache)
```

`serein distribution status` and `serein distribution inspect <path>`
(the main CLI) are the only distribution surfaces safe to run in any
environment - read-only, no network, no build.
