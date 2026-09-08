# Installer Architecture (S7.1)

## Mission

> Integrate the mature Ubuntu installer stack; do not invent another
> installer engine.

S7.1 turns the S7.0 bootable Serein live-media prototype into a system
that can perform a **real installation onto an explicitly selected
target disk**, while proving every non-target disk remains untouched.
The central safety invariant, enforced as code (not merely
documented):

```text
NO EXPLICIT TARGET  =  NO DESTRUCTIVE INSTALL
```

## Pipeline

```
Serein Live ISO
      |
explicit target selection            <- serein.installer.identity
      |
disk identity verification           <- serein.installer.identity (TOCTOU revalidation)
      |
destructive-operation plan           <- serein.installer.planner
      |
safety gate                          <- serein.installer.diskguard
      |
Ubuntu installer backend (curtin/Subiquity, via a rendered autoinstall.yaml)
      |
Serein installed system
      |
reboot
      |
installed Serein boot                <- serein.installer.bootcheck
```

This is the same Discover -> Resolve -> Plan -> Validate -> Apply ->
Verify -> Record lifecycle `docs/architecture/installer-contract.md`
already mandates for every future mutating operation in this
repository:

| Contract stage | S7.1 module |
|---|---|
| Discover | `serein.installer.diskprobe` (real `lsblk` inventory) |
| Resolve | `serein.installer.identity` (stable fingerprint + TOCTOU re-match) |
| Plan | `serein.installer.planner` (baseline Serein Alpha layout) |
| Validate | `serein.installer.diskguard` (ancestry + GRUB-target safety gate) |
| Apply | `serein.installer.renderer` + `serein.installer.isoprep` (QA-only) + real QEMU (Layer B only) |
| Verify | `serein.installer.bootcheck` (installed-system boot marker) |
| Record | `serein.installer.payload` (`/etc/serein/install-state.json`) + `serein.installer.evidence` |

## Module map

```
src/serein/installer/
  models.py      dataclasses only - DiskInfo, TargetDiskIdentity, InstallPlan,
                  InstallerLayerBEvidence, etc. Every disk/target field
                  defaults to the SAFE side of the safety invariant.
  diskprobe.py    real lsblk-based disk inventory (read-only, injectable
                  CommandRunner, fail-soft)
  identity.py     stable target fingerprint capture + TOCTOU re-match
                  (resolved/not_found/ambiguous/changed)
  diskguard.py    the safety gate: ancestor_disk(), classify_protection(),
                  validate_target_selection(), validate_plan_ancestry(),
                  validate_grub_target() - DiskGuardError + the Section 37
                  failure-code taxonomy
  planner.py      build_install_plan() (baseline GPT+ESP+root layout) +
                  validate_plan() (composes every diskguard check)
  renderer.py     Subiquity/curtin autoinstall.yaml rendering - QA-only
                  by construction (every entrypoint requires an explicit
                  qa_mode=True)
  payload.py      the S7.2 handoff marker + runtime-only QA credential
                  generation (real openssl passwd -6, never a hardcoded
                  hash)
  isoprep.py      extracts a built S7.0 QA ISO, embeds the rendered
                  autoinstall.yaml, rebuilds the QA-install ISO variant
  bootcheck.py    boots the INSTALLED target disk on its own (no install
                  medium) and requires a genuine reached-target marker -
                  reuses S7.0's proven marker-evaluation primitives
  evidence.py     InstallerLayerBEvidence assembly/write/load
  closure.py      the one explicit, fail-closed Installer Layer-B
                  closure gate
  doctor.py       serein installer doctor checks (PASS/WARN/FAIL/SKIP)
  status.py       serein installer status
  __main__.py     python -m serein.installer - the explicit, QA-CI-only
                  heavy tooling entrypoint (render-autoinstall,
                  prepare-qa-install-iso, boot-check, evidence,
                  closure-gate)
```

## CLI surface

The interactive `serein` CLI only ever exposes **read-only** installer
commands - never a command that destroys storage:

```text
serein installer status              backend/disk-probe availability
serein installer disks [--json]      real disk inventory
serein installer doctor [--json]     PASS/WARN/FAIL/SKIP diagnostics
serein installer plan --target <selector> [--json]
                                       preview a validated destructive
                                       plan for an EXPLICIT target -
                                       never writes/wipes/formats/
                                       mounts/installs anything
```

There is deliberately no `serein install <target>` command. Actual
execution happens only via `python -m serein.installer` (heavy,
explicit, QA-CI-only tooling - see `docs/installer/install-modes.md`)
driving a real QEMU boot of a prepared QA-install ISO, the same way
`serein.distribution`'s `boot-smoke` never runs from the interactive
CLI either.

## Scope boundary

S7.1 owns: installer integration, disk inventory, stable disk
identity, explicit target selection, protected-disk classification,
destructive-operation planning/validation, installer config rendering,
installer invocation via QEMU, Serein installation payload handoff,
target bootloader placement, automated VM install validation,
installed-system boot validation.

S7.1 does **not** own: S7.2 first-boot provisioning, S7.3 recovery,
Focus Apply, hardware resource enforcement, Tor routing activation,
automatic cyber tooling, Secure Boot signing, a custom kernel, advanced
encryption UI, multi-disk RAID, dual-boot partition shrinking, Windows
partition modification, or production unattended installation. See
`docs/installer/known-limitations.md`.

## Why integrate, not reinvent

Per `docs/roadmap.md`'s "Integrate -> Measure -> Replace" architecture
invariant (already applied by S7.0 to the base-image/livecd-rootfs
question - `docs/distribution/upstream-installer-research.md`), S7.1
never forks Subiquity and never writes a custom partitioning/install
engine. The Serein layer owns target identity, safety policy, plan
validation, and evidence; upstream continues owning actual filesystem
creation, package/system installation, and GRUB installation mechanics
(curtin, invoked by Subiquity from a rendered autoinstall config -
Section 4).
