# Known Limitations (S7.0; updated by the S7.0R Layer-B closure corrective)

## Scope limitations (by design - Section 83)

- **Not a public release.** See
  `docs/distribution/licensing-and-release-boundary.md` - the project
  has no selected license; every artifact this phase produces is a
  private development alpha.
- **Project license unresolved.** No `LICENSE` file exists; a public
  release is blocked on the project owner making that decision, not on
  anything S7.0 could implement.
- **Installer branding not final.** S7.0 deliberately does not fork or
  re-theme the Ubuntu/Subiquity installer UI (Section 3) - it may still
  show upstream Ubuntu visuals throughout.
- **Serein payload embedded ≠ installed.** The payload manifest on
  built media (`serein/payload-manifest.json`) proves files are present
  on the medium, never that they have been installed into any target
  operating system - see `docs/distribution/payload.md` (Section 55).
- **First boot not implemented.** No `serein-firstboot.service` or
  equivalent exists anywhere in this repository - that is S7.2.
- **Recovery not implemented.** No recovery partition, restore image,
  rollback partition, or factory reset exists - that is S7.3.
- **Focus runtime not implemented.** Serein Focus remains
  `planning_only` on any media this phase builds - no cgroup write, no
  systemd slice, no boot-time focus auto-selection
  (`docs/focus/architecture.md` is unchanged by S7.0).
- **Secure Boot not verified.** `REAL_SECURE_BOOT=NOT_PERFORMED` in
  every report this phase produces unless an actual Secure-Boot-enabled
  VM/hardware test occurred (Section 31, 97) - "signed upstream boot
  chain files are preserved" is a structural claim this phase can and
  does make (`docs/distribution/iso-build.md`), which is a different,
  weaker claim than "Secure Boot was validated."
- **Physical hardware boot not verified.** `REAL_PHYSICAL_BOOT=NOT_PERFORMED`
  - out of scope without a disposable physical machine (Section 96).

## Real Layer B validation status - this implementation pass (S7.0R)

This pass, like the original S7.0 pass before it, ran entirely inside a
Windows/MSYS2 (Git Bash) development environment with no `xorriso`,
`squashfs-tools`, `mtools`/`dosfstools`, `qemu-system-x86_64`,
`pycdlib`, or `jq` installed, and no root/admin path to install them
without user action. All five S7.0R correctives (A-E) are implemented
and exercised by a fully injectable fake-`xorriso`/fake-QEMU Layer-A
test suite (`tests/test_distribution.py`) - including a genuinely real,
unmocked wheel build against this repository - but the *real* Layer-B
sequence (download the actual ~6.0 GB ISO, build both real ISOs, run
the strict inspector against real xorriso output, boot the QA ISO in
real QEMU) has not been executed in this environment:

| Field | Status | Why |
|---|---|---|
| `REAL_UBUNTU_26_04_BASE_VERIFICATION` | **NOT_PERFORMED** | The real ~6.0 GB `ubuntu-26.04.1-desktop-amd64.iso` was never downloaded in this environment - only `SHA256SUMS`/`SHA256SUMS.gpg` (small text files) were fetched and GPG-verified, which authenticates the *pinned checksum value*, not the ISO's actual bytes. See `docs/distribution/security.md`. |
| `REAL_SEREIN_PRODUCTION_ISO_BUILD` | **NOT_PERFORMED** | Requires the verified base ISO (above) plus `xorriso`, neither available here. |
| `REAL_SEREIN_PRODUCTION_ISO_INSPECTION` | **NOT_PERFORMED** (real .iso, strict) / lenient structural inspection **DID** run against a fixture extracted tree (`distribution/test-fixtures/extracted-tree-ok/`, all checks pass) | No real built ISO exists to inspect yet; the strict inspector's logic is proven against a fully-faked `xorriso` (`tests/test_distribution.py::TestStrictInspector`), not real tool output. |
| `REAL_SEREIN_QA_BOOT_ISO_BUILD` | **NOT_PERFORMED** | Same blocker - the QA-variant rebuild step (`qa_boot.prepare_qa_variant` + a second `xorriso -as mkisofs`) is proven against the real fixture tree's real `grub.cfg` (`tests/test_distribution.py::TestQaBoot`), never against a real base image's GRUB config. |
| `REAL_SEREIN_QEMU_BOOT` | **NOT_PERFORMED** | `qemu-system-x86_64` is not installed in this environment; no ISO exists to boot regardless. |
| `REAL_INSTALLER_REACHABILITY` | **NOT_PERFORMED** | Depends on the above. |
| `REAL_UEFI_BOOT` | **NOT_PERFORMED** | No OVMF firmware image available. |
| `REAL_BIOS_BOOT` | **NOT_PERFORMED** | No QEMU available. |
| `REAL_SECURE_BOOT` | **NOT_PERFORMED** | No Secure-Boot-capable test environment. |
| `REAL_PHYSICAL_BOOT` | **NOT_PERFORMED** | No disposable physical machine. |

**A WSL2 Ubuntu-24.04 environment is present on this machine** with real
network access and ~895 GB free disk - genuinely capable of running the
full Layer B pipeline (`apt install xorriso squashfs-tools qemu-system-x86
ovmf jq`, then the real fetch/verify/build/inspect/boot-smoke sequence).
It was not used in this pass because installing packages there requires
`sudo`, which requires a password this session does not have and should
not request interactively - see `docs/distribution/s7-roadmap.md` for
how to complete Layer B as an explicit follow-up once that one blocker
is cleared (a human running one `apt-get install` command via `!` is
the only missing step).

**`.github/workflows/iso-smoke.yml` is now PR-runnable** (S7.0R
Corrective A - opt in with the `run-iso-smoke` label, or trigger it
manually), which is the intended way to actually obtain real Layer-B
evidence before merge. It has not been run in this pass: this
repository's `gh` CLI remains unavailable in this environment
(consistent with every prior phase this session), so neither applying
the label nor manually dispatching the workflow was possible from here.

```text
S7_0R_LAYER_B_TRIGGER_READY=true
S7_0R_LAYER_B_RUN=NOT_PERFORMED_EXTERNAL_TRIGGER_REQUIRED
```

Per Section 51/79: **`S7_0_READY_FOR_MERGE=NO`** until Layer B evidence
above turns to real PASS results - this document states that blocker
honestly rather than fabricating success. The independent reviewer is
expected to apply the `run-iso-smoke` label (or manually dispatch the
workflow) and observe the real run.

## Implementation-scope limitations (this alpha pass specifically)

- **The UEFI-evidence heuristic in the strict inspector has not been
  validated against real Ubuntu 26.04.1 `xorriso` output.**
  `_UEFI_EVIDENCE_MARKERS` in `inspect.py` (`appended_part_as_gpt`,
  `--interval:appended_partition`) is a best-effort heuristic derived
  from the generally-documented modern Ubuntu hybrid-ISO layout, not
  copied from a real report this environment could produce (no
  `xorriso` installed here). The first real Layer-B run should save
  the actual `-report_el_torito` output (the workflow already does
  this, to `dist/el-torito-base-report.txt`) and confirm or correct
  this marker list.
- **The QEMU boot-smoke harness does not terminate early on a positive
  marker.** Section 49 of the S7.0R corrective explicitly makes this
  optional ("You may improve... do not sacrifice log integrity") - the
  harness still runs for its full bounded timeout even after a success
  marker appears in the log, rather than killing QEMU immediately. A
  future pass could add early termination without changing the
  positive-evidence contract.
- **`SOURCE_DATE_EPOCH` is not yet threaded through the actual `xorriso`
  invocation.** `BuildManifest.source_date_epoch` exists as a schema
  field and hook (Section 18), but `run_build` does not currently
  compute it from the git commit timestamp or pass it to xorriso -
  byte-level timestamp normalization remains future work.
- **Byte-for-byte reproducibility is not claimed or measured.** Only
  logical reproducibility (Section 17) is claimed - see
  `docs/distribution/iso-build.md`.
- **Only the Desktop edition was researched/pinned.** The Server live
  ISO's checksum was also verified during research (see
  `docs/distribution/base-image.md`) but is not the pinned default;
  switching editions would require updating `distribution/base-image.json`
  deliberately, never silently (Section 5).
- **Signature verification is scripted but not exercised end-to-end
  against the real ISO file** in this pass - `verify-base-image.sh`'s
  GPG step was designed and its key-fetch/verify logic was proven
  against the real `SHA256SUMS`/`SHA256SUMS.gpg` files (see
  `docs/distribution/security.md`), but has not yet been run as part of
  a full `fetch -> verify -> build` sequence against the actual ISO.
- **`distribution/build-config.json`'s `required_tools` reflects only
  the current extraction/overlay/rebuild pipeline** (`xorriso`,
  `python3`, `curl`, `jq`) - it does not include `squashfs-tools`/
  `mtools`/`dosfstools` because the current pipeline does not touch the
  SquashFS live filesystem or EFI/FAT partition contents at all
  (Sections 34-36). A future pass that needs to modify either would
  need to add those tools deliberately, with the explicit staged
  extract/verify/modify/repack process Section 35 requires.
