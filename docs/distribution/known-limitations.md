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

## Real Layer B validation status (S7.0RM)

**A real Layer-B run has now occurred.** After the S7.0R pass, an
independent reviewer applied the `run-iso-smoke` label to PR #9,
triggering `.github/workflows/iso-smoke.yml` for real on a
GitHub-hosted `ubuntu-latest` runner:

```text
RUN_ID=34131219916
RUN_NUMBER=2
HEAD=fae55499ab992978347a1440f229c1e7d5620ed6
EVENT=pull_request
RESULT=FAILURE
```

The exact-head checkout worked correctly (`EXPECTED_SOURCE_SHA` ==
`ACTUAL_CHECKED_OUT_SHA`, both `fae55499...`), confirming Corrective
A's PR-trigger and exact-head model are sound. The run then failed at
the **disk space preflight**: the runner had ~13 GiB free
(`AVAILABLE_KB=13599352`) against the S7.0R workflow's fixed 20 GiB
requirement, before any base ISO was ever downloaded. The subsequent
evidence-assembly step then crashed with `FileNotFoundError` on a
production manifest that legitimately never got written - a second,
independent defect (Corrective B).

**S7.0RM fixes both** (see `docs/distribution/iso-build.md`'s "Storage
model" and this file's own "Implementation-scope limitations" below for
exactly what changed) and adds Correctives C-G on top. This development
environment still has no `xorriso`/`qemu`/`squashfs-tools` installed
(unchanged from every prior pass this session), so the corrective code
itself has only been validated via the fully injectable fake-`xorriso`/
fake-QEMU Layer-A test suite (`tests/test_distribution.py`, 1199 tests
passing) plus one genuinely real, unmocked wheel build against this
repository - not against a second real Layer-B run:

| Field | Status | Why |
|---|---|---|
| `REAL_UBUNTU_26_04_BASE_VERIFICATION` | **NOT_PERFORMED** (this pass) | The real run above never reached the download step (blocked at preflight). The ~6.0 GB ISO has still never been downloaded from this development environment either. |
| `REAL_SEREIN_PRODUCTION_ISO_BUILD` | **NOT_PERFORMED** | Same blocker. |
| `REAL_SEREIN_PRODUCTION_ISO_INSPECTION` | **NOT_PERFORMED** (real .iso, strict) / lenient structural inspection **DID** run against a fixture extracted tree, all checks pass | The strict inspector's logic is proven against a fully-faked `xorriso` (`tests/test_distribution.py::TestStrictInspector`), never real tool output. |
| `REAL_SEREIN_QA_BOOT_ISO_BUILD` | **NOT_PERFORMED** | The in-place QA transition (Corrective A/B) is proven against the real fixture tree's real `grub.cfg`, never a real base image's GRUB config. |
| `REAL_SEREIN_QEMU_BOOT` | **NOT_PERFORMED** | No ISO exists to boot yet. The marker-aware monitor (Corrective D) is proven with a fully faked `Popen`/clock (`tests/test_distribution.py::TestBootSmoke`), never a real QEMU process. |
| `REAL_INSTALLER_REACHABILITY` | **NOT_PERFORMED** | Depends on the above. |
| `REAL_UEFI_BOOT` | **NOT_PERFORMED** | No OVMF firmware image available locally; `--require-uefi` fail-closed logic is unit-tested, never exercised against real OVMF. |
| `REAL_BIOS_BOOT` | **NOT_PERFORMED** | No QEMU available. |
| `REAL_SECURE_BOOT` | **NOT_PERFORMED** | No Secure-Boot-capable test environment. |
| `REAL_PHYSICAL_BOOT` | **NOT_PERFORMED** | No disposable physical machine. |

**A WSL2 Ubuntu-24.04 environment is present on this machine** with real
network access and ~895 GB free disk - genuinely capable of running the
full Layer B pipeline locally. Not used in this pass for the same
reason as every prior pass this session: installing packages there
requires `sudo`, which requires a password this session does not have
and should not request interactively.

**PR #9 retains the `run-iso-smoke` label.** Per Section 51 of the
S7.0RM corrective, `iso-smoke.yml` already supports `pull_request:
synchronize` while the label remains attached - pushing this
corrective's commits should automatically trigger a new Layer-B run on
the new exact HEAD, with no separate action needed. This repository's
`gh` CLI remains unavailable in this environment (consistent with every
prior phase this session), so this pass could not itself observe that
new run's outcome.

```text
S7_0RM_LAYER_B_TRIGGER_READY=true
S7_0RM_LAYER_B_RUN=NOT_PERFORMED_FROM_THIS_ENVIRONMENT (auto-triggered by push; outcome must be observed externally)
```

Per Section 74: **`S7_0_READY_FOR_MERGE=NO`** until a Layer-B run
against the exact final S7.0RM commit turns every `REAL_*` field above
to a genuine PASS - this document states that blocker honestly rather
than fabricating success. The independent reviewer should watch the
automatically-triggered run (or re-apply/re-trigger it if needed) on
the new HEAD.

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
- **Resolved in S7.0RM**: the QEMU boot-smoke harness now terminates
  immediately once a positive marker is observed (Corrective D), rather
  than running for its full bounded timeout regardless - see
  `docs/distribution/boot-validation.md`.
- **The ephemeral-runner-cleanup allowlist has not been validated
  against a real `ubuntu-latest` runner's actual installed SDK paths.**
  `/usr/local/lib/android`, `/usr/share/dotnet`, `/opt/ghc`,
  `/usr/local/.ghcup`, `/usr/share/swift` are GitHub's own
  commonly-documented preinstalled tool locations, not independently
  confirmed present-and-large on the specific runner image this
  workflow uses - the cleanup step existence-checks each one and skips
  silently if absent, so an inaccurate guess only means *less* space is
  reclaimed, never an error, but the actual `SPACE_RECLAIMED_KB` this
  produces has not been observed from a real run yet.
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
