# Memory Policy: ZRAM and Swap

## Detection

`src/serein/hardware/memory_policy.py` reads:

- `/proc/swaps` — every active swap backend, disk-backed or ZRAM alike.
  A device is classified `"zram"` by name (the kernel reports ZRAM swap
  as a plain `partition` type, indistinguishable from a real disk
  partition by the `Type` column alone).
- `/sys/block/zram*/{disksize,comp_algorithm}` — existing ZRAM device
  size and active compression algorithm.
- `/etc/systemd/zram-generator.conf` / `.conf.d/` — existing
  `systemd-zram-generator` configuration, even before any `zram*` device
  has actually materialized from it.

Nothing here ever modifies swap. `serein hardware plan`'s `memory.zram`
action is the only place a ZRAM *recommendation* appears, and it is
read-only (`status: "APPLY"` is a proposal, not an action taken).

## Why ZRAM, not "swap is bad"

Serein treats RAM, ZRAM, and disk-backed swap as three complementary
mechanisms, not a hierarchy where one replaces the others:

- **RAM** is fastest and finite.
- **ZRAM** is a compressed, in-RAM swap device — much faster than disk,
  costs CPU time for compression, and is a good buffer for short memory
  pressure spikes.
- **Disk-backed swap** is slower but has no RAM cost and is the correct
  backstop for genuinely running out of both RAM and ZRAM's compressed
  capacity.

Serein never disables or removes existing disk swap. If disk swap is
already present, the plan reports it and leaves it exactly as is.

## Sizing policy: upstream's own defaults, not an invented ratio

`hardware/defaults/zram-generator.conf` (a planning-only repository
artifact, not installed anywhere in S2 — see `resources.py`):

```ini
[zram0]
zram-fraction = 0.5
max-zram-size = 4096
compression-algorithm = zstd
swap-priority = 100
fs-type = swap
```

These are **exactly `systemd-zram-generator`'s own documented defaults**
(`zram-generator.conf(5)`), not a Serein invention. The reasoning, worked
through by RAM tier (`zram-fraction * RAM`, capped at `max-zram-size`):

| RAM tier | `RAM / 2` | Capped at 4096 MiB | Resulting ZRAM | As % of RAM |
|---|---|---|---|---|
| ≤ 8 GiB | ≤ 4096 MiB | no cap needed | up to 4 GiB | up to 50% |
| 16 GiB | 8192 MiB | capped | 4 GiB | 25% |
| 32 GiB | 16384 MiB | capped | 4 GiB | 12.5% |
| 64+ GiB | 32768+ MiB | capped | 4 GiB | ≤ 6.25% |

This tapers exactly the way a sound policy should: aggressive relative
protection on memory-constrained machines, a small, low-overhead safety
net on machines where memory pressure is rare. Choosing to follow
upstream's own formula (rather than a competing ratio) is itself the
"Integrate → Measure → Replace" choice — there is no measured evidence
yet that Serein's own users need a different curve, so there is no
reason to diverge from the tool's own maintainers' guidance.

**Compression algorithm:** `zstd`, matching `systemd-zram-generator`'s own
default and offering the best compression ratio of the commonly-available
in-kernel algorithms (`lzo`, `lz4`, `zstd`). Actual kernel-module
availability is not verified live in S2 (documented in
`docs/hardware/known-limitations.md`) — a future Apply step would need to
confirm `zstd` is present in `/sys/block/zram0/comp_algorithm`'s available
list before writing the config, falling back to `lz4` if not.

**Priority:** `100`, high enough that the kernel prefers ZRAM over any
existing disk swap (which typically defaults to priority `-2`) without
needing to touch the disk swap's own priority at all.

## Conflict avoidance (Section 22 of the S2 brief)

`planner._zram_action()` checks for an existing ZRAM device **or** an
existing `zram-generator.conf`/`.conf.d` *before* proposing anything. If
either is present, the action is `NOOP` with the detail "ZRAM already
configured on this host; Serein will not layer a second, competing
implementation" — Serein never recommends installing a second ZRAM tool
on top of Ubuntu's own. `serein hardware doctor`'s
`hardware_existing_zram` check reports the same fact independently
(`PASS` if found, `SKIP` if not configured at all — never `FAIL` for
simply not having ZRAM yet).

## Swappiness

S2 deliberately makes **no swappiness recommendation of any kind** —
neither a global change nor a profile-specific one. `vm.swappiness`'s
interaction with ZRAM is genuinely workload- and kernel-version-dependent,
and no measurement exists yet to justify a specific value over the kernel
default. Per the S2 brief: "it is acceptable for S2 to leave kernel
default unchanged," and there is no folklore constant here to be found —
this is intentional, not an oversight.
