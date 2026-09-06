# ADR-0007: ZRAM and Swap Strategy

## Status

Accepted (corrected by S2R — see "S2R correction" below)

## S2R correction

Live validation against the real `systemd-zram-generator` package
(1.2.1-2, Ubuntu 26.04) found that `zram-fraction`/`max-zram-size` are
**obsolete options** (confirmed via the installed `zram-generator.
conf(5)` man page's own "OBSOLETE OPTIONS" section) and that
`compression-algorithm = zstd` was **not actually upstream's default**
(the real default is to leave it unset, deferring to the kernel). Both
claims below are corrected; the sizing *value* (`min(ram/2, 4096)`) and
the swap-priority *value* (`100`) were never wrong — only the option
names and the compression-algorithm claim were. See
`docs/validation/s2r/zram-validation.md` for exact evidence and
`docs/hardware/memory-policy.md` for the corrected config.

## Context

Nearly every "Linux desktop optimization" guide has an opinion on ZRAM
sizing, and they disagree wildly — "RAM", "2x RAM", "half of RAM", fixed
values regardless of machine class. S2 needs one defensible answer, and
needs to never propose a second, competing ZRAM implementation when
Ubuntu (or the user) has already configured one via
`systemd-zram-generator`, which is the current standard mechanism on
recent Ubuntu/Debian systems.

## Decision

- **Sizing:** adopt `systemd-zram-generator`'s own documented default —
  `zram-size = min(ram / 2, 4096)` (the *current*, non-obsolete option;
  verified against the real, installed 1.2.1-2 package) — rather than an
  invented ratio. See `docs/hardware/memory-policy.md` for the resulting
  size at each RAM tier and why the taper (aggressive on small-RAM
  machines, small-and-cheap on large-RAM ones) is sound.
- **Algorithm:** left unset, deferring to the kernel default — verified
  this, not `zstd`, is what the tool itself does when unconfigured.
  Serein will only pin an algorithm once a real benchmark shows a
  measured reason to (`docs/hardware/planning-and-safety.md`).
- **Priority:** `100` — verified to also be the tool's own documented
  default, pinned explicitly for self-documentation, high enough that
  the kernel prefers ZRAM over typical disk-swap priorities (`0`/`-2`)
  without touching disk swap.
- **Conflict avoidance:** detect an existing active ZRAM device
  (`/sys/block/zram*` or `/proc/swaps`) or an existing generator config
  with a real `[zramN]` section — scanned across all eight real search
  paths (`/usr/lib`, `/usr/local/lib`, `/etc`, `/run`, each with a base
  `.conf` and a `.conf.d/*.conf` form; verified against the installed
  man page) — *before* proposing anything. An empty `conf.d/` directory
  or one containing only non-`.conf` files is correctly treated as "no
  configuration", not a false positive. If any real source exists, the
  plan action is `NOOP`, explicitly stating Serein will not layer a
  second implementation.
- **Virtualization:** confirmed live that `systemd-zram-generator`'s own
  generator refuses to run under container-detected virtualization
  (which includes WSL2) — Serein's own WSL/container guard for ZRAM is
  therefore based on verified upstream behavior, not an assumption.
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
  (`hardware/defaults/zram-generator.conf`) is planning-only in S2/S2R;
  its real installation target (`/etc/systemd/zram-generator.conf.d/
  90-serein.conf`) **was** verified for package-ownership collision
  against a live Ubuntu 26.04 archive in S2R (`dpkg-query -S` after a
  real install, plus an archive-wide `apt-file` search) — confirmed
  unowned.
- A genuinely useful finding from live validation: installing
  `systemd-zram-generator` alone already produces Serein's exact
  intended policy via the package's own shipped default config. Serein's
  drop-in exists for self-documentation and future-divergence headroom,
  not because the package default is insufficient.

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
