# Power and Thermal Policy

## Power source and battery detection

`src/serein/hardware/power_policy.py` reads `/sys/class/power_supply/`
directly (S0's `power.py` already established this as the base-truth
source for `has_battery`/`on_ac_power`; S2 adds per-battery `capacity`
and `status`). No dependency on UPower or any D-Bus service is required
for this — sysfs alone is sufficient and is what UPower itself reads
under the hood.

## power-profiles-daemon integration, not replacement

Per ADR-0008, Serein integrates with `power-profiles-daemon` (PPD) —
already Ubuntu's default power-management daemon (also driving KDE's
`powerdevil` in Plasma 6) — rather than building a competing mechanism or
defaulting to TLP.

**Detection, not control:** PPD exposes no sysfs readback of its active
profile — only D-Bus does, and Serein's hardware layer has never called
an external command or D-Bus method anywhere in S0–S2. `power_policy.py`
therefore detects PPD's mere *presence* via stable on-disk markers (the
`power-profiles-daemon.service` unit file, or the `powerprofilesctl` CLI
binary), and the planner's `power.ppd_profile` action always reports
`current: null` — Serein does not fabricate a value it cannot read.

### Profile mapping

| Serein profile | PPD profile | Why |
|---|---|---|
| `balanced` | `balanced` | Direct match. |
| `dev` | `balanced` | Sustained mixed workload — not the platform's power-saver mode. |
| `cyber` | `balanced` | Same reasoning as `dev`. |
| `ai` | `balanced` | See below — `ai`'s performance bias is expressed through the CPU EPP action instead. |
| `battery` | `power-saver` | Direct match; the one profile PPD-availability guarantees ("balanced" and "power-saver" exist on every system that has PPD at all). |

**Why `ai` does not request PPD's `performance` profile:** PPD's own
`performance` profile is hardware-dependent (Section 29 of the S2 brief:
"do not assume PPD offers a `performance` profile on every machine") and
whether it exists on a given system can only be discovered over D-Bus.
Rather than guess and risk the request silently failing or behaving
unexpectedly, the `ai` profile's real performance bias is expressed
through `cpu.epp` (`docs/hardware/cpu-policy.md`), which *is* backed by
directly-readable sysfs evidence (`energy_performance_available_
preferences` tells us definitively whether `performance` is supported on
this exact CPU). This is a deliberate, documented design choice, not an
oversight.

## Why not TLP

TLP is a mature, capable tool, but installing it alongside
`power-profiles-daemon` risks two power managers fighting over the same
kernel knobs — a well-known real-world failure mode for both tools.
Ubuntu 26.04 ships PPD by default; Serein integrates with what's already
there (ADR-0002, upstream-first) rather than adding a second daemon.
TLP remains a documented alternative to reconsider only if a measured gap
in PPD's coverage is found (Integrate → Measure → Replace) — not added
pre-emptively "just in case."

## Thermal: telemetry only, never control

`src/serein/hardware/thermal.py` reads `/sys/class/thermal/thermal_zone*`
(type + temperature) and checks for the presence of any `hwmon` sensor.
This is purely descriptive: `serein hardware doctor`/`capabilities`
surface whether thermal telemetry exists at all
(`thermal_telemetry` capability), but **no plan action in S2 reads a
temperature value or changes behavior based on one.** The S2 brief is
explicit that Serein must never disable throttling, raise thermal limits,
modify EC behavior, or override fan curves — S2 does not even attempt
threshold-based warnings yet, since that would require deciding what
threshold is meaningful across wildly different hardware without
measurement. A future phase that adds "avoid switching to a
high-performance plan while hot" logic should treat this file as the
detection layer to build on, not extend it with control logic in place.

## Virtualization

No power-source or PPD action is virtualization-guarded the way CPU/
storage actions are: a laptop VM guest with a real virtual
`power_supply` battery device is a legitimate, meaningful scenario (some
hypervisors do expose one), and PPD detection is a presence check, not a
hardware-ownership claim. If neither exists in the guest, the natural
`SKIP`/absent-capability path already produces the honest result without
a special-cased guard.
