# Boot Validation (S7.0 Sections 30-31, 44-49, 92-97)

## Two separate questions

1. **Structural inspection** (`serein.distribution.inspect`) - do the
   expected artifacts exist where convention says they should (EFI boot
   image, boot catalog, media marker, payload manifest)? This is a
   read-only filesystem/ISO9660 check, never a boot attempt.
2. **Real boot evidence** (`serein.distribution.bootsmoke`) - does the
   medium actually boot in QEMU, evidenced by a positive marker read
   back from a serial console log?

Neither one is allowed to stand in for the other; a report that only
performed (1) must never claim (2) passed.

## QEMU boot-smoke harness

```bash
./distribution/scripts/boot-smoke.sh <path-to-iso> [--ovmf-code PATH]
```

wraps `python -m serein.distribution boot-smoke`, which calls
`serein.distribution.bootsmoke.run_boot_smoke`:

- **No target disk ever** (Section 44, 92) - the QEMU command
  (`build_qemu_boot_command`) never includes `-hda`/`-drive` for a
  writable disk; only `-cdrom <iso>` (read-only boot medium) and,
  optionally, a **read-only** `pflash` OVMF firmware image for UEFI.
- **Finite timeout, always** (Section 48) - `run_boot_smoke` passes
  `timeout=` to the subprocess call and catches
  `subprocess.TimeoutExpired`, reporting `status="fail"` with whatever
  partial serial log was captured; it never hangs indefinitely.
- **Positive evidence only** (Section 46) - `evaluate_boot_log` requires
  one of `DEFAULT_SUCCESS_MARKERS` (systemd "Reached target ..." lines)
  to literally appear in the captured serial log. "The QEMU process
  didn't crash" is never treated as success -
  `tests/test_distribution.py::TestBootSmoke::test_process_alive_alone_is_never_success`
  regresses this directly.
- **KVM when available, TCG fallback otherwise** (Section 49) -
  `boot-smoke.sh` probes `/dev/kvm` and only passes `--accel kvm` if it
  is readable/writable; normal unit-test CI never requires KVM.

## QA-only serial boot entry (Section 47)

`distribution/boot/qa-serial-entry.cfg` is a template menu entry that
adds `console=ttyS0,115200n8` to the normal live-boot kernel command
line, so kernel/systemd log lines are observable on QEMU's serial port.
It is:

- structurally separate from the normal graphical boot entry (a
  distinctly-titled `menuentry`, never the default),
- never sets `autoinstall`,
- never touches any disk,

and `tests/test_distribution.py::TestAutoinstallSafety::test_qa_serial_entry_template_itself_is_safe`
regresses that the template itself carries no autoinstall trigger.

## Boot-mode claims (Section 30-31, 94-97)

This alpha pass makes no boot-mode claim beyond what was actually
tested. See `docs/distribution/known-limitations.md`'s `REAL_*` fields
for the exact status of each:

- `REAL_UEFI_BOOT` - requires an OVMF firmware image, not present in
  this development environment.
- `REAL_BIOS_BOOT` - requires QEMU, not installed in this development
  environment.
- `REAL_SECURE_BOOT` - requires a Secure-Boot-enabled VM/hardware
  environment; never claimed without one. "Signed upstream shim/GRUB/
  kernel files are preserved unmodified" (which S7.0's extraction/
  overlay approach does guarantee structurally, per
  `docs/distribution/iso-build.md`) is a different, weaker claim than
  "Secure Boot was validated" - this document does not conflate them.
- `REAL_PHYSICAL_BOOT` - out of scope without a disposable physical
  machine; not performed.

## What structural inspection alone proves (and does not)

`inspect_extracted_tree`/`inspect_iso_file` prove the medium's
*contents* are structurally consistent (marker present and well-formed,
payload hashes match, an EFI boot image and boot catalog exist at their
conventional paths). They do **not** prove the medium boots - that is
exactly why the boot-smoke harness exists as a separate, real-execution
step, and why `docs/distribution/known-limitations.md` reports
inspection and boot-smoke evidence as two distinct fields, never merged
into one "boot validated" claim.
