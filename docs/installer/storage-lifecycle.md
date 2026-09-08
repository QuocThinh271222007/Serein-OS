# Installer Layer-B Storage Lifecycle (S7.1R)

Real Layer-B run #1 (`RUN_ID=34216492634`) failed at `disk_preflight`:
the original model summed every large artifact this job ever creates
as though they all coexisted simultaneously (55 GiB required against a
real ~36.4 GiB available). They do not. This document records the real
lifecycle for every large artifact `installer-smoke.yml` creates, so
the preflight budget reflects actual simultaneous residency rather than
a naive total.

## Per-asset lifecycle

| Asset | Created at | Last real consumer | Safe release point |
|---|---|---|---|
| Base ISO (`cache/upstream/*.iso`) | `fetch-base-image.sh` | S7.0's own QA rebuild, inside `build-iso.sh` | Already released by `run_build(ephemeral_storage=True)` itself, before `build-iso.sh` even returns - verified directly against `src/serein/distribution/build.py`, never assumed |
| S7.0 extracted work tree (`build/work/extracted`) | `run_build()`'s own extraction step | The QA rebuild, inside the SAME `build-iso.sh` step | Right after "Build Serein Alpha ISO" succeeds - nothing reads it again (strict inspection re-extracts its own copy straight from the ISO *files*) |
| Production ISO (`dist/serein-alpha-*.iso`) | S7.0 build | Its own strict inspection | Right after "Strict-inspect production ISO" succeeds - no render/isoprep/fixture/install step ever reads it |
| QA ISO (`dist/serein-alpha-*-qa.iso`) | S7.0 build | `prepare-qa-install-iso` (isoprep's own source) | Right after "Prepare QA-install ISO" succeeds |
| QA-install extraction tree (`build/installer-work/qa-install-extracted`) | `isoprep.prepare_qa_install_iso`'s own extraction | The rebuild inside that SAME function call | Immediately - it never has a consumer beyond the call that created it |
| QA-install ISO (`dist/serein-alpha-*-qa-install.iso`) | `prepare-qa-install-iso` | `run-qa-install.sh` (attached as `-cdrom`) | Right after "Run real QA autoinstall" completes (Section 47: the install medium is removed before the installed-target boot check anyway) |
| Strict-inspection scratch (`dist/inspect-strict-work/{production,qa}/iso-strict-extract`) | `inspect_iso_file_strict` | Its own single invocation | Self-managed; only ever extracts `/serein` (a few MB), never the whole ISO content - does not meaningfully affect the peak |
| Protected/target qcow2 fixtures (`dist/installer-fixtures/*.qcow2`) | `create-fixture-disks.sh` | Every step from fixture creation through the final boot-check | End of job (negligible marginal cost once created; nothing larger follows) |
| Serial logs / evidence JSON | Various | Upload-artifact step | End of job (tiny) |

## Why the peak is NOT 55 GiB

The original model summed base ISO + production ISO + QA ISO +
QA-install extracted tree + QA-install ISO + both fixture disks'
*virtual* capacity, as if none of them were ever released and the
fixtures were fully allocated from the start. Per the table above:

- The base ISO and the S7.0 extracted tree are gone before the
  "Prepare QA-install ISO" step even begins.
- The production ISO is gone before "Render QA autoinstall config"
  begins.
- Fixture qcow2 images are sparse - their *virtual* capacity
  (4 + 8 = 12 GiB) is never a guaranteed host allocation; real
  allocated bytes are measured via `du -sh`
  (`installer/scripts/log-disk-usage.sh`) rather than assumed.

## The two real candidate peaks

1. **`ISOPREP_PEAK_GIB` (21 GiB)** - inside "Prepare QA-install ISO":
   the QA ISO (source, 7), a full second extraction of it
   (`qa-install-extracted`, 7), and the QA-install ISO being written
   (7), all alive at once.
2. **`INSTALL_PEAK_GIB` (13 GiB, estimated)** - during "Run real QA
   autoinstall": the QA-install ISO (still present, 7) plus the real
   allocated growth of the fixture disks as curtin populates the
   target (`FIXTURE_QCOW2_ALLOCATED_GIB`, budgeted generously at 6 -
   the live QA-install medium's own squashfs is the practical upper
   bound on how much a base install can populate; the protected disk's
   real allocated size never meaningfully changes, which is the entire
   point of the safety proof).

`installer-smoke.yml`'s preflight step computes both and uses their
real maximum (`PEAK_GIB = max(ISOPREP_PEAK_GIB, INSTALL_PEAK_GIB) = 21`),
plus a non-zero `SAFETY_MARGIN_GIB = 6`, giving `REQUIRED_GIB = 27` -
comfortably under Run #1's real ~36.4 GiB available, with genuine
headroom, and not merely lowered until CI happened to pass.

## Cleanup mechanism

`installer/scripts/release-artifact.sh` is the one canonical release
helper (mirrors `distribution/scripts/record-failure.sh`'s "one
canonical helper, never scattered ad-hoc" discipline): it accepts only
exact, already-known repo-relative paths, refuses anything absolute or
containing a `..` traversal segment, and fails closed if the resolved
path (after symlink resolution) would land outside the repository
root. It never uses `sudo` - every path it releases is owned entirely
by the job's own unprivileged build/dist workspace, never the
qemu-nbd-backed fixture disks (which have their own root-confined
cleanup inside `create-fixture-disks.sh`, following the same
S7.0RM6-established discipline of repairing/removing only within an
already-confined scratch subtree).

## Telemetry

`installer/scripts/log-disk-usage.sh <stage-label>` runs after every
major stage (`after_cleanup`, `after_base_fetch`, `after_s7_0_build`,
`after_prod_inspection`, `after_qa_inspection`, `after_qa_install_iso`,
`after_fixture_creation`, `after_install`, `after_target_inspection`),
logging real `available_kb`/`used_kb` plus `du -sh` of whatever large
artifacts currently exist. It never fails merely because an optional
path is already gone - most of them are *expected* to be gone by later
stages, once their own release step has run. A real run's logs give
real numbers this estimate can be corrected against, exactly like
S7.0's own preflight arithmetic was revised more than once after real
evidence (see `docs/distribution/known-limitations.md`'s run history).

## S7.1R5: transient raw-conversion temp files

`installer/scripts/hash-disk-image.sh` (Objective A/D of the S7.1R5
corrective) creates one transient, disposable raw-format copy of
whichever disk it is currently hashing (via `qemu-img convert`),
deleted immediately (trap-based cleanup) before the script returns -
never more than one such temp file alive at a time. Reasoned peak
impact (not measured - `REQUIRED_GIB` is deliberately NOT bumped this
round without real telemetry justifying it, per this document's own
established discipline): the largest single call converts the target
disk (virtual capacity 8 GiB) while the QA-install ISO (7 GiB) is
still alive and both fixture qcow2s are resident - a reasoned new
candidate peak of roughly `7 + 6(FIXTURE_QCOW2_ALLOCATED_GIB) + 8 = 21`
GiB, at parity with (not exceeding) the existing `ISOPREP_PEAK_GIB=21`
this document already accounts for, so `REQUIRED_GIB=27` should retain
its existing real margin. This reasoning is unverified against a real
run - `log-disk-usage.sh`'s existing telemetry (unchanged this round)
is what will actually confirm or correct it from Run #6's real
`du`/`df` output, exactly as this document's own established
discipline requires.
