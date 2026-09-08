# Known Limitations (S7.1)

## Real Layer-B validation status (S7.1R3)

**Three real Installer Layer-B runs have occurred**, each exposing and
fixing a real defect:

```text
Run 3 (after S7.1R2):
  RUN_ID=34224122883, RUN_NUMBER=4
  HEAD=957542960c849d404796ef7c1027052cdc1fe031
  RESULT=FAILURE - failure_stage=installer_timeout. R2's QEMU corrective
  is PROVEN: qemu_started=true, installer_userspace_reached=true, and
  the real guest kernel dmesg shows the intended topology exactly
  (virtio0=[vda] 4.00 GiB=protected, virtio1=[vdb] 8.00 GiB=target) -
  no drive/device swap, no /dev/vdX confusion. The QEMU process was
  killed by the wrapper's own `timeout` after the full 1800s budget
  (qemu_exit_status=124).

  PROVEN root cause (direct evidence, not inferred): the real captured
  kernel command line was exactly
  `BOOT_IMAGE=/casper/vmlinuz console=ttyS0,115200n8 --- splash` - no
  `autoinstall` token anywhere. `serein.installer.isoprep.prepare_qa_install_iso`
  wrote `autoinstall.yaml` at the extracted tree's root but never
  patched the boot entry to actually trigger unattended installation -
  the boot entry it inherits unmodified is
  `serein.distribution.qa_boot`'s own "Serein Alpha
  (qa-serial-boot-smoke)" entry, which is EXPLICITLY documented and
  coded (Section: "never add autoinstall and never touch any disk
  target") to never carry that parameter, since it exists only for
  S7.0's own read-only boot-smoke test. The medium therefore booted
  into a completely normal interactive Ubuntu Desktop live session -
  matching every other observed symptom: the full stock snap set
  loading (firefox, thunderbird, gnome-46-2404, ubuntu-desktop-bootstrap,
  ...; Serein Alpha's base is `edition: "desktop"` per
  `distribution/base-image.json`, so this alone is not evidence of a
  wrong ISO - Ubuntu Desktop DOES ship its own curtin/subiquity-server
  via the `ubuntu-desktop-bootstrap` snap, whose apparmor profiles
  visibly loaded in the serial log, but were never invoked in
  unattended mode), the target disk hash never changing (curtin was
  never told to run), and the run exhausting its 30-minute timeout
  idling in a live session that had nothing to unattend.

  Fixed by S7.1R3: `prepare_qa_install_iso` now further patches its
  OWN independent copy of the extracted tree (never
  `serein.distribution.qa_boot` itself, whose "never autoinstall"
  contract must stay intact for S7.0's boot-smoke use) to add the bare
  `autoinstall` kernel parameter to that one specific boot entry - see
  `serein.installer.isoprep._enable_autoinstall_on_qa_entry`.

  Real Run #3 also showed the protected disk's hash changed
  (`protected_disk_modification_count=1`) while the target's did not.
  INFERRED (not proven): this is a downstream symptom of the SAME root
  cause, not an independent storage-selector defect - a normal
  interactive Ubuntu Desktop live session runs `udisks2.service`
  ("Disk Manager") with automount active, and even a brief, harmless
  mount of the protected fixture's pre-existing ext4 partition
  (superblock last-mount-time/journal-replay) is a well-known way to
  produce a small hash delta with zero deliberate content change - a
  real unattended Subiquity autoinstall run explicitly does NOT load
  the full desktop/automount stack this evidence shows running. This
  is not yet proven; a real Run #4 (which will, for the first time,
  actually reach curtin/Subiquity) is the genuine test of whether it
  recurs. The protected-disk safety invariant itself
  (`protected_disk_hash_unchanged`/`protected_disk_modification_count`)
  is unchanged and unweakened by this pass - see
  `docs/installer/protected-disks.md`.
```

## Real Layer-B validation status (S7.1R2)

**Two real Installer Layer-B runs have occurred**, each exposing and
fixing a real defect:

```text
Run 1 (after S7.1 initial integration):
  RUN_ID=34216492634, RUN_NUMBER=1
  HEAD=27f144f47667c0efe493fe2212437af4ab742dad
  RESULT=FAILURE - failure_stage=disk_preflight. The original preflight
  model summed every large artifact this job ever creates as though
  they all coexisted simultaneously (55 GiB required) against a real
  ~36.4 GiB available (FREE_SPACE_AFTER_CLEANUP_KB=38180984,
  AVAILABLE_KB=38180956). Fixed by S7.1R - see
  docs/installer/storage-lifecycle.md for the real per-asset lifecycle
  analysis and the corrected, real-simultaneous-residency preflight
  model (REQUIRED_GIB=27).

Run 2 (after S7.1R):
  RUN_ID=34219273003, RUN_NUMBER=2
  HEAD=6b9b04155f060a135a7bab0a8a12b26cdd58644a
  RESULT=FAILURE - failure_stage=install_failed. The corrected S7.1R
  storage model is PROVEN: disk_preflight/base_fetch/base_verify/
  production_iso_build/production_iso_inspection/qa_iso_build/
  qa_iso_inspection/autoinstall_render/qa_install_iso_prepare/
  protected_qcow2_created/target_qcow2_created/fixture_topology_verified
  all PASSED for real. The real QA autoinstall QEMU run itself then
  failed - protected/target disk hashes were unchanged before/after
  (protected_disk_modification_count=0, target_disk_changed=false),
  meaning no evidence exists that the installer ever reached
  destructive target-disk work. `qa-install-serial.log` alone did not
  carry enough diagnostic evidence to determine why. High-confidence
  causal hypothesis (never confirmed against the real exact stderr,
  which this run did not separately retain - RUN_2_EXACT_QEMU_STDERR=
  NOT_RETAINED): `run-qa-install.sh`'s legacy
  `-drive if=virtio,...,serial=...` convenience shorthand is a known
  QEMU compatibility hazard - the shorthand does not reliably plumb
  `serial=` through to the device model on every QEMU version. Fixed
  by S7.1R2 - see docs/installer/vm-validation.md's "QEMU startup
  evidence" section for the corrected modern split backend/device
  topology, the new bounded startup probe, and the new precise
  qemu_startup/installer_timeout/installer_execution failure
  classification (replacing the old, undifferentiated
  `install_failed`) that a third run will need to make full use of.
```

Because Run 2 failed inside the real QEMU install step, nothing past
it was exercised: `REAL_INSTALLER_EXECUTION`,
`REAL_PROTECTED_DISK_HASH_PROOF`, `REAL_TARGET_LAYOUT_INSPECTION`, and
`REAL_INSTALLED_BOOT` are all still `NOT_OBSERVED` for a corrected
run - Run 2 is evidence of the QEMU-drive-identity defect S7.1R2
fixes, never evidence that the real destructive install itself works.
Run 2 also exposed two secondary, non-causal release/cleanup step
failures (execution continued into the real install attempt
regardless) - their exact root cause is likewise `NOT_RETAINED`
(no `gh` CLI access from this development environment to inspect the
real job log); S7.1R2 hardened every `Release ...` step to record a
real, first-failure-wins-safe `artifact_release_failed` stage on any
future recurrence (visible in evidence, never silently swallowed)
without ever masking the real causal blocker or aborting the job over
a best-effort cleanup step.

Run 1's evidence-fidelity defect (`target_explicit`/
`target_identity_revalidated`/`target_disk_attached` recorded as
`true` unconditionally even though disk_preflight failed before any of
those stages could possibly have run) remains fixed as of S7.1R -
`target_disk_attached` is no longer a hardcoded structural constant,
and every one of these three fields in `installer-smoke.yml`'s
evidence-assembly step is gated on the real stage that would have
proven it.

A third real Installer Layer-B run against the S7.1R2 commit is
required before any `REAL_*` field below can honestly move past
`NOT_OBSERVED`. This development environment has no `qemu-img`/
`qemu-nbd`/`curtin`/Subiquity/`qemu-system-x86_64` installed
(`REAL_LOCAL_QEMU=NOT_AVAILABLE` - consistent with every S7.0 round of
this repository's history, see
`docs/distribution/known-limitations.md`), so `installer-smoke.yml`
itself has only ever been validated structurally and via real `bash`
execution against a stub `qemu-system-x86_64` from here:

| Field | Status | Why |
|---|---|---|
| `LAYER_A` | **PASS** | Full `pytest`/`ruff`/`mypy`/`verify.sh` against `src/serein/installer/`, `tests/test_installer.py`, and every `installer/scripts/*.sh` file (real `bash -n` syntax check, plus real `bash` execution of `run-qa-install.sh`/`release-artifact.sh` against stub tools on `PATH`). |
| `REAL_DISK_PREFLIGHT` | **PASS** (Run 2) | Proven for real - the S7.1R storage model is closed pending new contrary evidence (Section 15 of the S7.1R2 corrective). |
| `REAL_QEMU_STARTUP` | **FAIL** (Run 2, hypothesized cause) | The exact real defect this S7.1R2 pass targets. Not yet re-run for real against the corrected topology. |
| `INSTALLER_BACKEND_AVAILABLE` | **NOT_OBSERVED** | `curtin`/Subiquity not installed in this environment; `serein.installer.doctor` correctly reports `SKIP`, never a fabricated pass. |
| `REAL_INSTALLER_EXECUTION` | **NOT_OBSERVED** | Requires a real GitHub Actions run of `installer-smoke.yml` that gets past the corrected QEMU startup. |
| `REAL_TARGET_DISK_INSTALL` | **NOT_OBSERVED** | Same. |
| `REAL_INSTALLED_SYSTEM_BOOT` | **NOT_OBSERVED** | Same. |
| `PROTECTED_DISK_MODIFICATION_COUNT` | **NOT_OBSERVED** (0 in Run 2, but vacuously - the install never reached destructive work) | The hashing/comparison logic itself is unit-tested (`tests/test_installer.py::TestEvidence`), and Run 2 did hash a real qcow2 pair before/after a real (failed) run - but a modification count of 0 here is not yet a positive proof of anything, since no destructive work was ever attempted. |

Per this repository's own established closure discipline (see every
S7.0 round's final report), this document states that gap honestly
rather than fabricating success. `python -m serein.installer` and the
main `serein installer` CLI are real, tested Layer-A code; the actual
`qemu-nbd`/`parted`/`mkfs`/`curtin` shell mechanics in
`installer/scripts/*.sh` and `installer-smoke.yml` are carefully
reasoned but **unexercised** pending a real CI run - exactly the
position S7.0's `boot-smoke.sh`/`iso-smoke.yml` were in before their
first real Layer-B run, and expected to need a similar corrective
iteration once real evidence exists.

## Expected S7.1 Alpha limitations

```text
physical hardware installation      NOT_PERFORMED (Section 53)
Secure Boot                          NOT_PERFORMED
disk encryption (LUKS/TPM)           not implemented (Section 16)
RAID / LVM / ZFS                     not implemented (Section 16)
automatic dual boot                  not implemented (Section 56)
partition resize/shrink              not implemented (Section 56)
BitLocker-aware installation         not implemented (Section 56)
advanced manual partition editor     not implemented
NVMe edge cases beyond the parser    only the naming CONVENTION is
                                       tested (nvme0n1/nvme0n1p1); no
                                       real NVMe hardware/qcow2 variant
                                       has been exercised
USB bridge identity quirks           not exercised - id_path probing
                                       is a best-effort /dev/disk/by-path
                                       scan, never validated against
                                       real USB-to-SATA/NVMe bridge
                                       hardware, which is known to
                                       sometimes hide or duplicate
                                       serial/WWN reporting
```

These are legitimate, intentional deferrals - never converted into a
fake PASS.

## `openssl passwd` argv exposure (Section 35)

`serein.installer.payload.generate_qa_credential` passes the freshly
generated plaintext QA password as a command-line argument to
`openssl passwd -6`. This is visible, for the brief duration of that
one process, to anything else with process-listing access on the same
host. Accepted only because this function is intended exclusively for
the single-tenant, ephemeral Layer-B CI runner, and is never called
from any interactive or production code path (the interactive `serein`
CLI has no command that could ever reach it). A future hardening could
pass the password via `openssl passwd -stdin` instead, which the
current `serein.development.runner.CommandRunner` protocol does not
support (no stdin parameter) - deferred rather than extending that
shared protocol speculatively in this pass.

## Renderer schema fidelity (Section 25-26)

`serein.installer.renderer.render_autoinstall_storage_config` follows
curtin's documented "storage config version 2" action schema
(`disk`/`partition`/`format`/`mount` actions with `match`/`wipe`/
`ptable`/`grub_device`/`size`/`fstype` keys), but this has not been
validated against a real `curtin`/Subiquity invocation in this
environment - mirrors the exact caveat pattern S7.0 already applied to
its own UEFI-evidence heuristic
(`docs/distribution/upstream-installer-research.md`). If a real
Layer-B run shows Subiquity rejecting the rendered config, that is a
new, narrowly-scoped defect to fix on its own real evidence, not
something this pass could pre-empt without a real installer to test
against.

## Windows/install-media classification (Section 13)

`serein.installer.diskprobe._classify_windows` is a best-effort label/
filesystem heuristic (FAT32 + a label containing "system"/"efi" ->
`windows_efi_detected`; a label containing "recovery"/"winre" ->
`windows_recovery_detected`; any NTFS signature -> contributes to
`windows_detected`). It has never been run against a real Windows
installation's actual partition labels, which are not standardized and
can vary by Windows version, OEM, and locale. The safety invariant
(`docs/installer/protected-disks.md`) never depends on this
classification being correct - it is diagnostic/warning evidence only.

## Disk-space preflight arithmetic (Section 50)

`installer-smoke.yml`'s preflight requirement (`REQUIRED_GIB=55`) is a
documented, named-component estimate, not a measured peak - S7.0's own
preflight number was revised twice (S7.0RM, S7.0RM4) after real runs
exposed the actual peak was different from the initial estimate.
Expect the same here once a real run produces real `df`/`du` evidence.

## No physical hardware install validation this phase (Section 53)

Real installation, for this phase, means real installer execution
against real virtual block devices under QEMU. Physical external-disk
testing remains `PHYSICAL_HARDWARE_INSTALL=NOT_PERFORMED` for initial
S7.1 closure - the final end-to-end physical validation is deferred
until after the installer + firstboot + recovery chain (S7.1 + S7.2 +
S7.3) is available and explicitly reviewed (Section 54: this
implementation phase must not access or alter any real external disk).
