# Distribution Architecture (S7.0)

## Mission

Prove Serein can become a reproducible distribution artifact, without
yet building a custom installer, first-boot system, or recovery system:

```
Ubuntu 26.04 LTS upstream ISO
        v
verified immutable base
        v
Serein distribution overlay
        v
Serein metadata/payload
        v
ISO assembly
        v
ISO structural validation
        v
VM boot validation
        v
reproducible Serein Alpha media
```

## What S7.0 is not

- Not a public release (`docs/distribution/licensing-and-release-boundary.md`).
- Not a fork of the Ubuntu/Subiquity installer UI.
- Not a first-boot provisioning system (S7.2).
- Not a recovery/rollback system (S7.3).
- Not a claim that Serein is an official Ubuntu flavor.

## Pipeline (`src/serein/distribution/`)

```
base.py       pinned base-image contract + fail-closed checksum verification
payload.py    resource-entry collection (hashed) + wheel build (subprocess, explicit)
overlay.py    allowlisted overlay application onto an extracted ISO tree
iso.py        boot-flag derivation (from the real base image's own el-torito
              report) + xorriso extract/rebuild command construction
build.py      the single canonical build pipeline (run_build) - orchestrates
              the above, fails closed at the first unsafe/unverified step
manifest.py   build-manifest assembly + <iso>.manifest.json/.sha256 recording
inspect.py    read-only structural inspection (extracted tree or real .iso)
bootsmoke.py  bounded QEMU boot-validation harness, positive-marker only
safety.py     static autoinstall-safety and credential-scan regressions
pathsafety.py shared traversal/symlink-escape/safe-cleanup primitives
status.py     read-only `serein distribution status` builder
```

Nothing in this list downloads anything or runs a build as a side
effect of import - see Section 12 ("no silent network downloads") and
`docs/distribution/iso-build.md` for the one canonical build entrypoint.

## Immutability of the upstream base

```
cache/upstream/
    ubuntu-26.04.1-desktop-amd64.iso   (never modified in place)

build/work/
    extracted/                          (a copy - overlay/payload land here)

dist/
    serein-alpha-26.04-amd64.iso        (build output)
    serein-alpha-26.04-amd64.iso.manifest.json
    serein-alpha-26.04-amd64.iso.sha256
```

`cache/`, `build/`, and `dist/` are all git-ignored (see `.gitignore`) -
none of these are ever committed to the repository.

## Payload vs. installed - a boundary that matters (Section 55)

"Serein payload is embedded on the media" is never the same claim as
"Serein payload is installed into a target OS." S7.0 proves the former
only. Making the latter true is S7.1/S7.2 territory - see
`docs/distribution/known-limitations.md`.

## Two validation layers (Section 50)

- **Layer A** (`tests/test_distribution.py`, runs in every normal CI
  job): configuration/schema validation, path-safety regressions,
  payload allowlist behavior, autoinstall/credential static scans, ISO
  command construction against fixtures. No network, no multi-GB
  download, no xorriso/qemu required.
- **Layer B** (explicit tooling only -
  `distribution/scripts/fetch-base-image.sh` through `boot-smoke.sh`):
  the real download, checksum/signature verification, ISO build, ISO
  inspection, and QEMU boot smoke. Never run implicitly. See
  `docs/distribution/boot-validation.md` and
  `docs/distribution/known-limitations.md` for this pass's actual
  Layer B evidence and blockers.

## Privacy/Cyber/Focus boundaries preserved on media (Sections 64-66)

Building or booting Serein media never enables Tor globally, never
auto-runs a cyber tool/container/VM, and never starts a Focus
enforcement daemon - the media boots into normal host networking with
Focus in `planning_only` mode, exactly like every S0-S6.5 CLI output
already guarantees on a running system. No code in
`src/serein/distribution/` touches Tor, cgroups, systemd units, or
network/firewall configuration.
