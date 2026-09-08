# Known Limitations (S7.1)

## Real Layer-B validation status

**No real Installer Layer-B run has occurred yet.** This development
environment has no `qemu-img`/`qemu-nbd`/`curtin`/Subiquity installed
(consistent with every S7.0 round of this repository's history - see
`docs/distribution/known-limitations.md`), so `installer-smoke.yml`
has only been validated structurally:

| Field | Status | Why |
|---|---|---|
| `LAYER_A` | **PASS** | Full `pytest`/`ruff`/`mypy`/`verify.sh` against `src/serein/installer/`, `tests/test_installer.py`, and every `installer/scripts/*.sh` file (real `bash -n` syntax check). |
| `INSTALLER_BACKEND_AVAILABLE` | **NOT_OBSERVED** | `curtin`/Subiquity not installed in this environment; `serein.installer.doctor` correctly reports `SKIP`, never a fabricated pass. |
| `REAL_INSTALLER_EXECUTION` | **NOT_OBSERVED** | Requires a real GitHub Actions run of `installer-smoke.yml`. |
| `REAL_TARGET_DISK_INSTALL` | **NOT_OBSERVED** | Same. |
| `REAL_INSTALLED_SYSTEM_BOOT` | **NOT_OBSERVED** | Same. |
| `PROTECTED_DISK_MODIFICATION_COUNT` | **NOT_OBSERVED** | The hashing/comparison logic itself is unit-tested (`tests/test_installer.py::TestEvidence`), but has never hashed a real qcow2 image before/after a real install. |

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
