# Physical Validation Preparation

Phase-7-completion Section 54-58. `PHYSICAL_VALIDATION=DEFERRED` -
this document is preparation, not execution. No destructive physical
test happens without the user explicitly providing and confirming the
target disk.

## Disk safety model - already real, already tested, unchanged

Physical installation reuses S7.1's existing safety contract
verbatim - this round adds no parallel confirmation system (Section
56 - "Do not implement a parallel confirmation system that weakens
S7.1"):

- **Explicit target resolution by identity** (`serein.installer.identity`,
  `serein.installer.diskprobe`) - model/serial/WWN/bus/size/removable/
  stable device properties, never `/dev/sdX` ordinal assumption, never
  first-disk or largest-disk fallback (Section 55 - absolute).
- **Protected-disk classification** (`serein.installer.diskguard`) -
  a disk not explicitly confirmed as the target is protected by
  construction.
- **Destructive-plan confirmation** (`serein.installer.planner`/
  `render-autoinstall`) - every destructive operation is enumerated
  and explicit before it can run.
- **Real, R1-R22-validated evidence extraction** - the entire
  `installer/scripts/extract-*.sh` forensic pipeline this project
  spent many corrective rounds hardening (most recently R22's
  storage-trigger reliability fix) is unchanged and ready to run
  against a real physical target exactly as it already runs against
  the QA virtual-disk fixtures.

Section 56's required pre-destructive-action display
(`TARGET_MODEL`/`TARGET_SERIAL`/`TARGET_WWN`/`TARGET_SIZE`/
`TARGET_BUS`/`TARGET_REMOVABLE`/`TARGET_STABLE_ID`/
`SYSTEM_DISKS_DETECTED`/`PROTECTED_DISKS`/`DESTRUCTIVE_PLAN`) is
already exactly what `serein installer plan --target <selector>`
prints today (`_cmd_installer_plan` in `src/serein/cli.py`) - no new
display mechanism was built, the existing one already satisfies this.

## Acceptance matrix (Section 57)

Execution is deferred; each row names the exact mechanism this
program already built that a real run would exercise.

| Area | Mechanism already built | Real-run evidence still needed |
|---|---|---|
| UEFI/GRUB | `serein.branding.grub_theme` (this round) | Real firmware boot, real `grub-mkconfig` compatibility |
| Plymouth | `serein.branding.plymouth_theme` (this round) | Real Plymouth render, real boot-time visibility |
| Installer | S7.1's full R1-R22 pipeline (unchanged) | Real physical-disk target resolution and destructive-plan execution |
| Disk selection | `serein.installer.identity`/`diskguard` (unchanged) | Real serial/WWN evidence on real hardware, never a virtual-disk analog |
| Reboot / boot installed system | S7.1's `boot-installed-target.sh` (unchanged, previously QA-only) | Real hardware boot without any install medium attached |
| SDDM / Plasma | `desktop/sddm/serein.conf` (S1, unchanged) | Real session start on real hardware |
| Network / Wi-Fi / Bluetooth / audio / GPU / suspend-resume | Out of this program's scope entirely | Real hardware compatibility evidence (Section 93 - explicitly allowed to defer) |
| Fastfetch | `serein.branding.fastfetch` (this round) | Real render (never validated against a real `fastfetch` binary - see `docs/branding/known-limitations.md`) |
| Firstboot | `serein.firstboot` (reconciled + extended this round) | Real systemd oneshot execution, real second-boot non-reprovisioning proof |
| Dev/AI/Cyber/Veil | S3-S6 registration-only steps (unchanged) | Real capability detection on real hardware |
| Focus | `serein.focus.runtime` (this round) | Real cgroup v2 `CPUWeight`/`IOWeight` enforcement observation |
| Resource behavior | `serein.hardware.executor` (this round) | Real `powerprofilesctl`/zram-generator activation |
| Updates | `serein.release.repository` (this round, real signed round-trip already proven) | Real client-side `apt update`/`install` against a real or local test repository |
| Recovery | `serein.recovery` (this round) | Real deliberate corruption + repair on a real installed target |

## What this program does NOT claim

`PHYSICAL_INSTALL=PASS` is never set by this program. Nothing here
constitutes real hardware compatibility evidence for any component -
every "already built" cell above means "the mechanism exists and is
unit/integration tested against fixtures," never "proven on real
hardware."
