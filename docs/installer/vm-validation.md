# VM Validation Topology (S7.1 Sections 30-33, 42-52)

## Real Layer-B sequence

`.github/workflows/installer-smoke.yml` (label-gated on
`run-installer-smoke`, deliberately a *different* label from S7.0's
`run-iso-smoke` - this job is more expensive and must never run merely
because a PR wants the S7.0 ISO smoke test):

```text
checkout exact feature HEAD
  -> normal Layer-A verification (pytest/ruff/mypy, via ci.yml separately)
  -> build the S7.0 production + QA ISO (unmodified S7.0 pipeline)
  -> strict-inspect both (isolated scratch work-dirs - S7.0RM6)
  -> render a real QA-only autoinstall.yaml (explicit target/protected
     identities, --qa-allow-autoinstall)
  -> prepare the QA-install ISO variant (autoinstall.yaml embedded)
  -> create the two real fixture disk images
  -> record BOTH disks' pre-install sha256
  -> boot the QA-install ISO under real QEMU/OVMF against both disks
  -> real curtin/Subiquity performs the real installation
  -> record BOTH disks' post-install sha256
  -> strict-inspect the target disk's real partition layout
  -> remove the install ISO
  -> boot the installed target disk on its own (self-contained proof)
  -> [informational] also boot it with the protected disk still present
  -> assemble Installer Layer-B evidence
  -> enforce the Installer Layer-B closure gate
```

## Required topology (Section 30)

```text
QEMU
+-- Serein QA-install ISO (autoinstall.yaml embedded)
+-- disk-protected.qcow2   (MUST survive untouched)
+-- disk-target.qcow2      (the real installation target)
```

Explicit, fixed virtio serials are assigned to each disk
(`SEREIN-PROTECTED-DISK` attached first -> guest `/dev/vda`,
`SEREIN-TARGET-DISK` attached second -> guest `/dev/vdb` -
`installer/scripts/run-qa-install.sh`) so the rendered
`autoinstall.yaml`'s storage `match` stanza can reference the target
deterministically - the in-guest analog of the target-identity
contract's "prefer stable evidence" for a virtual disk that has no
real hardware serial of its own.

**S7.1R2**: each disk is attached via the modern split backend/device
QEMU form (`-drive if=none,id=serein_{protected,target}_backend,...`
+ `-device virtio-blk-pci,id=serein_{protected,target}_device,
drive=serein_{protected,target}_backend,serial=SEREIN-{PROTECTED,TARGET}-DISK`)
- never the legacy `-drive if=virtio,...,serial=...` convenience
shorthand, which real Layer-B run #2 (`RUN_ID=34219273003`) exposed as
a QEMU compatibility hazard. Each backend/device pair has an explicit,
deterministic id, so the two serials can never be silently swapped.
See `docs/installer/known-limitations.md`'s Run #2 entry and
`installer/scripts/run-qa-install.sh`'s own header comment for the
full rationale, and "QEMU startup evidence" below for the bounded
startup probe and diagnostic capture this corrective added.

## QEMU startup evidence (S7.1R2)

`installer/scripts/run-qa-install.sh` runs a bounded, non-destructive
startup probe (`-S`, frozen CPU, killed after a short window) using
the EXACT real command line before ever starting the real, timed
install - proving the command line/device model is valid without
waiting up to the full install timeout. QEMU's own stdout/stderr are
always captured to a dedicated diagnostic log
(`qa-install-qemu-stderr.log`/`qa-install-qemu-stdout.log`) -
independent of the guest `-serial` log
(`qa-install-serial.log`), which may not even exist if QEMU dies
during command-line parsing before the guest ever opens its console.

Every invocation - probe failure, real-run failure, or success -
writes `qa-install-qemu-result.env` (`qemu_exit_status`,
`qemu_accelerator`, `qemu_firmware`, `qemu_timeout_seconds`,
`qemu_serial_log_path`, `qemu_diagnostic_log_path`, `qemu_started`,
`qemu_elapsed_seconds`, `failure_stage`, `installer_userspace_reached`,
`serial_log_present`) - `installer-smoke.yml`'s "Run real QA
autoinstall" step folds this straight into its own step outputs and
uses the real, precise `failure_stage` the script computed
(`qemu_startup`/`installer_timeout`/`installer_execution` - never the
old, undifferentiated generic `install_failed`) as the recorded causal
blocker. `installer_userspace_reached` is a WEAK, diagnostic-only
heuristic (serial log contains any of a small set of early kernel/
init/Subiquity markers) - never used for real closure evidence, unlike
the installed-system boot check's own strong-marker requirement
(Section 20 of the S7.1R2 corrective).

`REAL_PHYSICAL_DISK_PASSTHROUGH=false` is enforced by construction:
every `-drive`/`-cdrom` argument anywhere in the workflow and in every
`installer/scripts/*.sh` script names a path the job itself just
created inside the ephemeral runner's workspace - never `/dev/sdX` or
any other physical device path (`tests/test_installer.py::TestInstallerSmokeWorkflow`
and `TestInstallerScriptsStatic` statically prove this for the
committed workflow/scripts).

## Storage lifecycle

See `docs/installer/storage-lifecycle.md` for the real per-asset
lifecycle analysis (created-at/last-consumer/safe-release-point) behind
the disk-space preflight requirement, and why it is a real
simultaneous-residency model rather than a sum of every artifact this
job ever creates.

## Fixture disks (Sections 31-32)

**`disk-protected.qcow2`** (`installer/scripts/create-fixture-disks.sh`) -
simulates an internal disk that must survive untouched: a real GPT, a
FAT32 ESP containing a Microsoft-style sentinel path
(`EFI/Microsoft/Boot/sentinel.txt` - exercising Windows classification
without shipping any Microsoft binary, per Section 31's explicit
allowance), and an ext4 data partition with its own sentinel file.

**`disk-target.qcow2`** - simulates the external installation target,
**pre-populated** with an existing layout (a real GPT + an existing
ext4 partition with sentinel data, standing in for Section 32's
"OLD_DEBIAN_DATA") - never a conveniently blank disk. A successful
install proves Serein intentionally *replaces* a pre-existing layout
only after explicit targeting.

## The central proofs (Sections 44-48)

```text
PROTECTED_DISK_SHA256_BEFORE == PROTECTED_DISK_SHA256_AFTER
PROTECTED_DISK_MODIFICATION_COUNT == 0

TARGET_DISK_SHA256_BEFORE != TARGET_DISK_SHA256_AFTER

target disk real partition layout: GPT + FAT32 ESP + ext4 root
  (installer/scripts/inspect-target-layout.sh - qemu-nbd read-only
  connect, blkid, disconnect; never a real mount write)

installed target boots on its own (no install medium, self-contained
  ESP+root - serein.installer.bootcheck), with a genuine reached-target
  marker (S7.0's proven marker fidelity, reused unchanged)

/etc/serein/install-state.json present on the installed root,
  firstboot_provisioning == "pending"
```

All of this is real, hash-based, filesystem-inspected evidence - never
inferred merely from installer log text or an overall QEMU exit code.

## What this development environment can and cannot prove

This repository's development environment has no `qemu-img`/
`qemu-nbd`/`curtin`/Subiquity installed, so `installer-smoke.yml`
itself has never been executed end to end from here - only its YAML
structure, and every Python module it drives, are proven (Layer A: see
`tests/test_installer.py`, including a real `bash -n` syntax check on
every `installer/scripts/*.sh` file). A real exact-head Layer-B run
against this workflow is required before S7.1 can be considered
merge-ready - see `docs/installer/known-limitations.md`.
