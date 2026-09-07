# Boot Validation (S7.0 Sections 30-31, 44-49, 92-97; S7.0R Correctives A/B/E)

## Layer-B trigger model (Corrective A)

Real boot validation (and the rest of Layer B) runs via
`.github/workflows/iso-smoke.yml` in exactly two situations:

- **`workflow_dispatch`** - manual, any time, optionally pinned to an
  exact `sha` input.
- **A pull request carrying the `run-iso-smoke` label** - opt-in per
  PR; a normal PR commit never triggers it. The job re-runs on every
  subsequent `synchronize` while the label stays attached, so a
  corrected HEAD is re-validated automatically.

It is deliberately `pull_request`, never `pull_request_target` (this
workflow runs code from the feature branch and must never execute with
write-capable secrets); `permissions: contents: read` is the only
permission granted, and no repository secret is required anywhere in
this pipeline.

**Exact-head guarantee**: the checkout step uses
`github.event.pull_request.head.sha` (never the default merge ref a
plain `pull_request` checkout would otherwise resolve to), and a
dedicated "Verify exact-head checkout" step prints
`EXPECTED_SOURCE_SHA`/`ACTUAL_CHECKED_OUT_SHA` and fails the job if
they differ - so a build manifest's `source_commit` can never silently
diverge from the SHA that was actually reviewed.

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

## QA-only serial boot entry actually built into a QA ISO (Section 47; S7.0R Corrective B)

A template file in Git never proves the *built* media uses it - S7.0R
makes this real. `serein.distribution.qa_boot.prepare_qa_variant`:

1. discovers the extracted tree's real GRUB config via
   `discover_grub_config` (a fail-closed candidate list - `QA_BUILD=BLOCKED`,
   never a guessed path, if none of the known candidates exist),
2. derives a new QA menu entry from the tree's own real production
   entry (`derive_qa_menuentry` reuses its actual `linux`/`initrd`
   paths, adds `console=ttyS0,115200n8` *before* the `---` init-arg
   separator so it is a real kernel parameter, and removes `quiet`),
3. prepends that entry and forces it to boot automatically
   (`install_qa_entry_as_default`: `set default="0"` + a short
   `set timeout` - never keyboard automation),
4. recomputes any stale internal checksum-catalog entry
   (`update_checksum_catalog_if_present` - Ubuntu's `md5sum.txt`, if
   present) for the one file it modified,

on a **copy** of the already-fully-assembled production extraction
tree - the canonical production tree is never touched. The result is
rebuilt into `serein-alpha-26.04-amd64-qa.iso` (same Serein payload,
same Ubuntu SquashFS/kernel/initramfs, same boot flags as the
production ISO - see `docs/distribution/iso-build.md`). The QEMU
boot-smoke harness always targets this QA ISO, never the canonical
production one (Section 20 - the two are reported as separate evidence
fields, never conflated).

`distribution/boot/qa-serial-entry.cfg` remains a documentation
template only (it explains the QA-entry shape and is itself scanned
for autoinstall-safety), but the actual QA ISO's boot entry is now
*derived at build time*, not copy-pasted from that file -
`tests/test_distribution.py::TestQaBoot` regresses the real derivation
path end to end.

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

## Strict real-ISO inspection (S7.0R Corrective E)

`inspect_iso_file`/`inspect_extracted_tree` above are lenient - a
`skip` (e.g. xorriso unavailable) does not fail
`InspectionReport.passed`, which is appropriate for a quick structural
sanity check. Layer-B **closure evidence** needs a stricter bar:
`inspect_iso_file_strict` (`python -m serein.distribution inspect
<iso> --strict --expected-source-commit <sha>`) requires every finding
to be exactly `"pass"` for `InspectionReport.strict_passed` to be true
- a `skip` counts against it exactly like a `fail` (Section 36 -
"SKIP must not count as PASS"). It:

- computes the real ISO file's own sha256 and checks it against any
  `<iso>.sha256`/`<iso>.manifest.json` sidecar (Section 40) - never
  trusts a sidecar without hashing the actual bytes,
- reads the real Primary Volume Descriptor via `xorriso -pvd_info` and
  requires the expected volume ID to actually appear in it,
- re-derives the real `-report_el_torito as_mkisofs` output and
  requires it to parse into at least one boot flag, plus a best-effort
  UEFI-evidence heuristic over that same report text (GPT-appended-
  EFI-System-Partition markers - Section 37; not validated against a
  real Ubuntu 26.04.1 report in this environment, since no xorriso is
  installed here - see `docs/distribution/known-limitations.md`),
- extracts `/serein` from the real ISO bytes via `xorriso -osirrox on`
  (never mounts the medium) into a scratch directory, and hashes
  **those extracted bytes** against the payload manifest - never the
  source repository (Section 39, the one honest way to prove the
  shipped media matches its own manifest).

Every one of these checks is unit-tested with a fully injectable fake
`xorriso` runner (`tests/test_distribution.py::TestStrictInspector`),
since this development environment has no real `xorriso` to validate
against - the *logic* is proven; validation against real Ubuntu
26.04.1 `xorriso` output remains outstanding Layer-B work (see
`docs/distribution/known-limitations.md`).
