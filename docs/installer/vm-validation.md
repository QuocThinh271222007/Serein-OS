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

## Disk diagnostic instrumentation (S7.1R4, revised S7.1R5)

Real Layer-B runs #3 and #4 both showed the protected qcow2's
CONTAINER hash changing (Run #5 then proved the R4 `readonly=on` fix
resolves that exact defect - see below). The plain container-level
measurement (`sha256sum` on the raw qcow2 file, still the one that
actually gates closure via `protected_disk_hash_unchanged`) cannot by
itself distinguish a real guest-visible content change from a
qcow2-format container-level artifact (e.g. lazy-refcount/dirty-bit
bookkeeping that can occur purely from a qcow2 image being opened for
write access, independent of any guest I/O).

`installer/scripts/hash-disk-image.sh` (called both immediately before
and immediately after the real install attempt, for BOTH the protected
AND target disks as of S7.1R5) separately measures:

- `container_sha256` - the existing raw-file measurement
- `logical_sha256` - the FULL guest-visible logical block content
- `esp_sentinel_sha256` / `data_sentinel_sha256` - the two real
  sentinel files `create-fixture-disks.sh` writes (on the TARGET disk,
  `data_sentinel_present` honestly flipping to `false` after a real
  successful install is itself expected/correct evidence - curtin
  replaces the original pre-populated partition table with Serein's
  own layout)

**S7.1R5 Corrective A**: the original S7.1R4 implementation
(`hash-protected-disk.sh`) used `qemu-nbd` + a real kernel `/dev/nbdX`
device node. Real Run #5 proved this fails in this exact CI
environment (it was the FIRST real workflow failure). The rewritten
`hash-disk-image.sh` removes the nbd/kernel-module/device-node
dependency entirely: `qemu-img convert` (pure userspace, no root, no
kernel module) produces a temporary raw file for the logical-content
hash, and `losetup -P` (the kernel's always-built-in loop driver, never
a separately loadable module like nbd) on that already-converted,
disposable temp file handles the sentinel-file checks. See the
script's own header comment for the full causal analysis. Every
hashing step's own failure is now also recorded via
`record-failure.sh` (secondary, non-blocking) - Run #5 also proved the
R4 version's failure was invisible to the evidence system entirely,
unlike every other failure-capable step in this workflow.

This remains purely diagnostic - it does not change what the closure
gate enforces (Section 16 of the S7.1R4 corrective: never silently
reinterpret the safety contract's semantics without explicit
justification from a real run's evidence). The before/after comparison
is persisted as `protected-disk-diagnostic.env` /
`target-disk-diagnostic.env` in the uploaded evidence artifact.

Separately, `installer/scripts/run-qa-install.sh` attaches the
protected qcow2 backend `readonly=on` (added in S7.1R4; Run #5 PROVED
this works at runtime - `protected_disk_hash_unchanged=true`,
`protected_disk_modification_count=0` - resolving the exact defect Run
#3 and Run #4 both showed). Do not remove this.

`installer/scripts/extract-installer-signals.sh` extracts a narrowly
scoped, targeted set of Subiquity/curtin/autoinstall/cloud-init/error
lines from the real serial log into
`qa-install-subiquity-signals.log`, so a future run's evidence
highlights the handful of lines that actually matter without requiring
a human to search a 400+KB raw transcript by hand.

**S7.1R5 Objective C**: `serein.installer.isoprep`'s boot-entry
patching now also adds `systemd.journald.forward_to_console=1`
alongside `autoinstall` (both via the same, generalized
`_add_kernel_token_to_qa_entry` mechanism R3's fix established). Since
`ubuntu-desktop-bootstrap`'s installer services (subiquity-server,
curtin, ...) run as ordinary systemd-managed snap services, their
stdout/stderr is captured by the systemd journal by default - this
forwards the whole journal to the serial console in real time, giving
the next real run's serial log actual Subiquity/curtin runtime
evidence instead of only kernel/systemd boot messages.

## S7.1R6: real install time budget, target capacity, closure preflight

Real Run #6 proved curtin actively progressing (real chroot/apt/dpkg
work) only ~31s before the previous 1800s timeout killed it - the
first real evidence authorizing a bounded increase. The real QA
install's own timeout is now 3600s
(`installer/scripts/run-qa-install.sh`'s default and the workflow's
explicit `--timeout`) - every OTHER timeout in this codebase (the
bounded, non-destructive startup probe; the installed-target boot
check) is a separately-bounded scope, deliberately unchanged.

The target fixture grew 8G -> 16G (see
`docs/installer/storage-lifecycle.md`'s "S7.1R6" section for the full
evidence and preflight-arithmetic reasoning) - the protected fixture
(4G) is unchanged.

`installer/scripts/inspect-target-layout.sh` was rewritten to use the
same `qemu-img convert` + `losetup -P` approach `hash-disk-image.sh`
already established (never qemu-nbd) - this script had never actually
executed successfully in any real run, and Run #6's real progress
makes Run #7 newly likely to finally reach it. Its output contract
(`target_esp_present`/`target_root_present`/`serein_core_present`/
`firstboot_provisioning`) is unchanged.

Evidence now also carries a purely-additive `secondary_failures` field
(`installer/scripts/record-secondary-failure.sh` +
`serein.installer.evidence`) - every diagnostic/cleanup step's own
failure remains visible without ever being able to overwrite (or be
confused with) the real primary blocker, which stays computed
exclusively by `distribution/scripts/record-failure.sh` (S7.0-owned,
unmodified).

## S7.1R7: primary/secondary wiring fix + bootstrap forensics

Real Run #7 (`RUN_ID=34335197624`) exposed a real defect in R6's own
secondary-failure wiring: every one of the 8 "secondary, non-blocking"
call sites called BOTH `distribution/scripts/record-failure.sh`
(PRIMARY) and `installer/scripts/record-secondary-failure.sh`
(SECONDARY) for the SAME event - meaning a genuinely non-blocking
cleanup/diagnostic failure (Run #7: a `build/work/extracted` release
failure) could occupy `dist/.failure_stage` if it happened
chronologically before the real installer blocker. Fixed: every
secondary call site now calls ONLY the secondary recorder. The
genuinely-primary call sites (`disk_preflight`, `base_fetch`, the real
install run itself, target-layout-inspection failure, etc.) are
unchanged. `distribution/scripts/record-failure.sh`'s own
first-failure-wins mechanism was never the defect - it was working
exactly as designed; the bug was which recorder each call site used.

Run #7 also revealed a ~3044s pre-Subiquity bootstrap window (real
snapd service startup timeouts/restarts, a desktop-security-center
hook/sanity-timeout failure, mass snap service removal/remount, a
task referencing a missing `/snap/snapd/current`, and a real 10-minute
NTP wait) - `WHY_RUN_7_SNAPD_SEEDED_TOOK_~3044s` remains genuinely
unproven. Two safe, zero-guest-modification-risk additions:

- `installer/scripts/extract-bootstrap-milestones.sh` (new) - bounded,
  host-side parsing of the already-captured serial log into a compact,
  machine-readable milestone/duration record
  (`qa-install-bootstrap-milestones.env`) for real run-to-run
  comparison (`snapd_seed_duration`,
  `curtin_runtime_before_qemu_exit`, etc.) - `qemu_timeout` specifically
  comes from the real, already-known `qemu_elapsed_seconds` host-side
  fact rather than being grep-matched, since QEMU's own termination
  message has no guest-console timestamp.
- `systemd.log_level=debug` added to the QA-install boot entry
  (chained onto the same proven kernel-parameter mechanism as
  `autoinstall`/journald-forwarding).

Live in-guest command execution (`snap changes`/`snap tasks`,
structured `systemctl show`, `timedatectl`, `ip route`) was
deliberately NOT implemented this round - it would require injecting a
new systemd unit into the live ISO's squashfs tree, a materially
larger, untestable-in-this-environment change with real risk of
breaking a future boot if done wrong. Deferred rather than risked
without real testing capability; see
`docs/installer/known-limitations.md`'s S7.1R7 entry for the full
reasoning.

## What this development environment can and cannot prove

This repository's development environment has no `qemu-img`/
`qemu-nbd`/`curtin`/Subiquity installed, so `installer-smoke.yml`
itself has never been executed end to end from here - only its YAML
structure, and every Python module it drives, are proven (Layer A: see
`tests/test_installer.py`, including a real `bash -n` syntax check on
every `installer/scripts/*.sh` file). A real exact-head Layer-B run
against this workflow is required before S7.1 can be considered
merge-ready - see `docs/installer/known-limitations.md`.
