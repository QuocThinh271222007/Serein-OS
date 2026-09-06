# ADR-0007: ZRAM and Swap Strategy

## Status

Accepted

## Context

Nearly every "Linux desktop optimization" guide has an opinion on ZRAM
sizing, and they disagree wildly — "RAM", "2x RAM", "half of RAM", fixed
values regardless of machine class. S2 needs one defensible answer, and
needs to never propose a second, competing ZRAM implementation when
Ubuntu (or the user) has already configured one via
`systemd-zram-generator`, which is the current standard mechanism on
recent Ubuntu/Debian systems.

## Decision

- **Sizing:** adopt `systemd-zram-generator`'s own documented defaults —
  `zram-fraction = 0.5`, `max-zram-size = 4096` (MiB) — rather than an
  invented ratio. See `docs/hardware/memory-policy.md` for the resulting
  size at each RAM tier and why the taper (aggressive on small-RAM
  machines, small-and-cheap on large-RAM ones) is sound.
- **Algorithm:** `zstd`, also `systemd-zram-generator`'s own default.
- **Priority:** `100` — high enough that the kernel prefers ZRAM over
  typical disk-swap priorities (`0`/`-2`) without touching disk swap.
- **Conflict avoidance:** detect an existing ZRAM device (`/sys/block/
  zram*`) or existing generator config (`/etc/systemd/
  zram-generator.conf[.d]`) *before* proposing anything; if either exists,
  the plan action is `NOOP`, explicitly stating Serein will not layer a
  second implementation.
- **Disk swap:** never disabled, never resized, never touched. Serein
  treats RAM/ZRAM/disk-swap as complementary, not a hierarchy.
- **Swappiness:** no recommendation at all, at any tier, for any profile.

## Consequences

- Serein's ZRAM policy is only as good as `systemd-zram-generator`'s own
  defaults are — if upstream ever changes its own recommended ratio, a
  deliberate decision is needed on whether Serein follows or diverges,
  rather than Serein silently drifting from what it originally copied.
- No per-workload ZRAM sizing exists yet (e.g. the `ai` profile does not
  request a larger ZRAM allocation for memory-heavy inference workloads)
  — deferred until a measured need is shown, per Integrate → Measure →
  Replace.
- The one repository artifact this produces
  (`hardware/defaults/zram-generator.conf`) is planning-only in S2; its
  real installation target (`/etc/systemd/zram-generator.conf.d/
  90-serein.conf`) has not been verified for package-ownership collision
  against a live Ubuntu 26.04 archive (documented in
  `docs/hardware/known-limitations.md`).

## Alternatives considered

**A Serein-specific ratio tuned per profile** (e.g. larger ZRAM for
`ai`). Rejected for S2: no measurement exists to justify diverging from
upstream's own default, and inventing one now would be exactly the kind
of unverified "optimization guide" tuning the S2 brief explicitly warns
against.

**`zram-tools`/`zramswap` (the older Debian/Ubuntu ZRAM mechanism).**
Rejected: `systemd-zram-generator` is the current standard mechanism this
phase targets integrating with; adding support for the legacy tool as
well would double the detection surface for a mechanism recent Ubuntu
releases have moved away from.
