# Profile Manifest Contract

## Purpose

A profile is a declarative description of a Serein capability bundle —
packages, services, configuration units, hardware preconditions, and
verification checks — validated against `schemas/profile.schema.json`.
Profiles exist so that future mutating behavior consumes structured data
instead of ad hoc shell scripts scattered across the repository.

## Three distinct states

Every profile-related surface (`serein profile list`, `ProfileEntry`) must
distinguish:

| State         | Meaning                                                              |
|---------------|-----------------------------------------------------------------------|
| `declared`    | The identity is named in the roadmap; no manifest exists yet.        |
| `implemented` | A manifest exists and validates, but may still apply nothing (S0).   |
| `active`      | The profile is the one currently applied to this host.               |

**S0 never reports `active=true` for anything** — activation (the code
path that would actually apply a profile) is not implemented. Reporting an
inactive profile as active would violate the "no fake PASS output" rule
that also governs `doctor`.

## Current scope (as of S6)

- `core` (S0): `profiles/core/core.profile.json`. Describes the
  unmodified host — empty `packages`/`services`/etc. — and exists to
  prove the schema and loader work end to end, not to do anything yet.
- `desktop` (S1): `profiles/desktop/desktop.profile.json`. A real
  package/configuration manifest with non-empty `packages`,
  `configuration_units`, and `verification_checks` — see
  `docs/desktop/architecture.md`. Still performs no installation; see
  `docs/desktop/installation-plan.md` for what "implemented" means here.
- `balanced`, `battery` (S2 baseline only — `dev`, `ai`, and `cyber`
  were since extended further, see below): `profiles/<id>/<id>.profile.json`.
  Each carries a real hardware resource-policy manifest (`packages:
  ["power-profiles-daemon", "systemd-zram-generator"]`, a shared
  `zram-generator-defaults` configuration unit, and the `hardware/*`
  doctor checks as `verification_checks`) — see
  `docs/hardware/architecture.md`. **"implemented" here means the
  hardware resource-policy layer is real** (detection, capability
  modeling, and `serein hardware plan` all work end to end); the
  application/tooling layer each of these profiles will eventually also
  carry remains entirely separate, unimplemented future work — a
  profile being `implemented` is not a claim that its whole eventual
  scope exists. `battery` additionally declares
  `hardware_conditions: ["battery_present"]`: on a battery-less host,
  `serein hardware plan battery` reports `profile_available: false`
  with a stated reason rather than pretending the profile applies.
- `dev` (S3): `profiles/dev/dev.profile.json` (version `0.2.0`). Unlike
  `balanced`/`ai`/`battery`/`cyber`, which still carry only their S2
  hardware resource-policy layer, `dev` was extended in S3 into a
  combined hardware-policy **and** software-workload manifest — still
  **one** canonical profile, not two competing manifests. Its
  `packages` field is the union of S2's hardware packages
  (`power-profiles-daemon`, `systemd-zram-generator`) and S3's default
  apt package set (`serein.development.packages.default_apt_packages()`,
  33 packages); its `configuration_units` field adds S3's
  `zed-settings-template`/`git-recommended-config` template resources
  alongside S2's `zram-generator-defaults`; its `verification_checks`
  field adds S3's six `development_*` doctor check ids alongside S2's
  ten hardware checks. See `docs/development/architecture.md` for what
  "implemented" means for this profile's software layer specifically —
  detection, capability modeling, and `serein dev plan` all work end to
  end, but there is still no Apply mechanism, same as the hardware
  layer.
- `ai` (S4): `profiles/ai/ai.profile.json` (version `0.2.0`). Extended
  the same way `dev` was in S3 — one canonical profile combining S2's
  hardware resource-policy layer with S4's AI-workstation software
  layer. Its `packages` field adds `ffmpeg` (the one real
  `ubuntu-repository` tool in S4's default manifest — NVIDIA/AMD/Intel/
  PyTorch/inference tooling all come from non-Ubuntu-archive sources,
  except CUDA Toolkit and ROCm, which live validation found are
  genuinely Ubuntu-repository packages on 26.04 but are still
  represented only in `serein.ai.packages`, not duplicated into this
  profile's `packages` array, since they are conditional on hardware
  presence rather than an unconditional default install like `ffmpeg`);
  its `verification_checks` field adds S4's seven `ai_*` doctor check
  ids alongside S2's ten hardware checks and S3's development checks
  reused by the separate `dev` profile. See `docs/ai/architecture.md`
  for what "implemented" means here — detection, capability modeling
  (including the hardware-present-vs-runtime-usable distinction), and
  `serein ai plan` all work end to end, but there is still no Apply
  mechanism.
- `cyber` (S5): `profiles/cyber/cyber.profile.json` (version `0.2.1`
  after the S5R micro corrective). **Important distinction, called out
  explicitly per the S5 brief:** this is the same `cyber` profile
  identity S2 already gave a hardware resource-policy manifest to
  (CPU/memory/storage policy biased for stable virtualization behavior,
  e.g. for running a VM-isolated workload) — S5 does not create a
  second "cyber" profile, it extends this one, exactly the pattern
  `dev` (S3) and `ai` (S4) already established. Its `packages` field is
  the union of S2's 2 hardware packages and S5R's 13-package Host Cyber
  Light default apt manifest (`serein.cyber.tools.default_apt_packages()`
  — `bind9-dnsutils`/`binutils`/`ethtool`/`file`/
  `libimage-exiftool-perl`/`mtr-tiny`/`netcat-openbsd`/`nmap`/
  `openssl`/`socat`/`tcpdump`/`tshark`/`whois`, live-validated on Ubuntu
  26.04 — see `docs/validation/s5/`). `wireshark` (the GUI package) is
  deliberately **not** part of this default set as of the S5R micro
  corrective: it is `recommended_tier="host"` (appropriate to have) but
  `default_install=False` (not forced onto every host) — see
  `docs/cyber/toolbox-strategy.md` and `docs/cyber/host-tooling.md`.
  Its `verification_checks` field adds S5's seven `cyber_*` doctor
  check ids (including the S5R-added `cyber_vm_readiness` check)
  alongside S2's ten hardware checks. See `docs/cyber/architecture.md`
  for what "implemented" means here — detection, capability modeling
  (host/toolbox/VM tiering, packet-capture privilege modeling), and
  `serein cyber plan` all work end to end, but there is still no Apply
  mechanism: no package is installed, no container or VM is created, no
  packet is captured, no network is scanned.
- `DECLARED_ONLY_PROFILES` (`src/serein/profiles/registry.py`) is empty
  as of S2 — every roadmap profile now has a manifest, and it remains
  empty through S6: **no `veil` profile manifest was added in S6**,
  deliberately (Section 90 of the S6 brief: "Do not automatically make
  Veil a global boot/network profile" — a registered profile Serein's
  own hardware-policy layer could apply implicitly would cut directly
  against S6's governing "privacy is opt-in, never an invisible global
  side effect" principle). `serein veil status`/`capabilities`/`plan`/
  `doctor` work without any profile registration, mirroring how S5's
  cyber *tooling* worked before S2 ever gave `cyber` a manifest.
  `DECLARED_ONLY_PROFILES` remains available for a future phase that
  does want profile-gated behavior.

## Manifest fields

See `schemas/profile.schema.json` for the authoritative shape. Fields such
as `packages`, `services`, `configuration_units`, `hardware_conditions`,
and `verification_checks` are contract surface for the installer
(`installer-contract.md`) to consume later; an empty array is a valid,
honest value for a profile that does nothing yet — it is not a placeholder
that silently gets treated as "not applicable."

## Loading

`profiles/registry.py:list_profiles()` reads every
`profiles/*/*.profile.json` file it can parse, falling back silently (not
crashing) on an unreadable or malformed manifest — a broken third-party
profile must never take down `profile list`. Manifest-backed entries take
precedence over a same-`id` declared-only stub.
