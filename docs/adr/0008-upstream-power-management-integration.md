# ADR-0008: Upstream Power-Management Integration (PPD, not TLP)

## Status

Accepted. Live-validated during S2R: `power-profiles-daemon` 0.30-2 is
confirmed available in the Ubuntu 26.04 archive, and its real installed
marker paths (`/usr/bin/powerprofilesctl`, `/usr/lib/systemd/system/
power-profiles-daemon.service`) exactly match what `power_policy.py`
already checked — no code change was needed here (see
`docs/validation/s2r/known-blockers.md`). The `ai`-profile design
decision below (no PPD `performance` request) was reviewed and is
provisionally reconfirmed, not changed.

## Context

Linux power management has two well-known, historically conflicting
approaches available on Ubuntu: `power-profiles-daemon` (PPD, the
freedesktop.org-backed daemon Ubuntu ships by default and that KDE
Plasma 6's `powerdevil` can drive directly) and `TLP` (a mature,
independently-configured tool with deep per-driver tuning). Running both
is a well-documented source of the two fighting over the same kernel
knobs. S2 needs one answer for how Serein's power-profile mapping
integrates with whichever is present.

## Decision

Integrate with **power-profiles-daemon only**. Serein:

- Detects PPD's presence via stable on-disk markers (its systemd unit
  file or the `powerprofilesctl` binary) — never via D-Bus, matching the
  read-only-filesystem-only detection style used everywhere else in this
  project.
- Never reads or fabricates PPD's *active* profile (not possible without
  D-Bus) — the planner's `power.ppd_profile` action always reports
  `current: null`.
- Maps four of five Serein profiles to PPD's `balanced` profile and
  `battery` to `power-saver` — the only two profiles guaranteed to exist
  on any system that has PPD at all. No Serein profile requests PPD's
  `performance` profile, since its existence is hardware-dependent and
  unverifiable without D-Bus (see `docs/hardware/power-policy.md` for why
  the `ai` profile's performance bias is expressed via CPU EPP instead).
- Does **not** install, configure, or even detect TLP. If PPD is absent,
  the `power.ppd_profile` action reports `SKIP` with the reason stated —
  Serein does not fall back to TLP automatically.

## Consequences

- On a system where PPD is absent and TLP is the user's own choice,
  Serein's power-profile plan action is inert (`SKIP`) — it neither
  fights TLP nor offers an alternative. This is intentional: Serein
  should never introduce a second power manager.
- If a real, measured gap in PPD's coverage emerges later (e.g. a
  hardware class where PPD genuinely underperforms TLP), that is grounds
  to revisit this ADR under Integrate → Measure → Replace — not a reason
  to hedge with dual support now.
- Thermal telemetry (`thermal.py`) is detected but never acted upon by
  any power-profile action — see `docs/hardware/power-policy.md`.

## Alternatives considered

**TLP as the primary integration target.** Rejected: Ubuntu 26.04 does
not ship TLP by default, and PPD is already the default, KDE-integrated
mechanism — choosing TLP would mean installing and configuring a second
power daemon where one already exists, violating upstream-first
(ADR-0002).

**Supporting both PPD and TLP, auto-detecting which is present.**
Rejected for S2: meaningfully doubles the surface area (two profile-name
vocabularies, two presence-detection paths, two sets of failure modes)
for a benefit — flexibility for TLP users — with no measured demand yet.
Revisitable later if real usage shows a need.
