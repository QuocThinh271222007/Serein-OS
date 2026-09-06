# Memory Policy: ZRAM and Swap

## S2R correction notice

S2's original claims about `systemd-zram-generator`'s defaults were
**wrong on two points**, found during S2R live validation against the
real package (`systemd-zram-generator` 1.2.1-2, Ubuntu 26.04 archive —
see `docs/validation/s2r/zram-validation.md` for exact evidence):

1. `zram-fraction`/`max-zram-size` are **obsolete options** — the real,
   installed `zram-generator.conf(5)` man page lists them under an
   "OBSOLETE OPTIONS" heading. The current option is `zram-size`, an
   arithmetic expression over a `ram` variable.
2. `compression-algorithm = zstd` was **not** actually upstream's
   default — the real man page states "If unset, none will be
   configured and the kernel's default will be used." S2 forced zstd
   and described it as matching upstream; that claim is removed.

Both are corrected below and in `hardware/defaults/zram-generator.conf`.

## Detection

`src/serein/hardware/memory_policy.py` reads:

- `/proc/swaps` — every active swap backend, disk-backed or ZRAM alike.
  A device is classified `"zram"` by name (the kernel reports ZRAM swap
  as a plain `partition` type, indistinguishable from a real disk
  partition by the `Type` column alone).
- `/sys/block/zram*/{disksize,comp_algorithm}` — existing ZRAM device
  size and active compression algorithm.
- **Every real `systemd-zram-generator` config search path** (verified
  against the installed `zram-generator.conf(5)` SYNOPSIS), not just
  `/etc/systemd/`:

  ```
  /usr/lib/systemd/zram-generator.conf
  /usr/local/lib/systemd/zram-generator.conf
  /etc/systemd/zram-generator.conf
  /run/systemd/zram-generator.conf

  /usr/lib/systemd/zram-generator.conf.d/*.conf
  /usr/local/lib/systemd/zram-generator.conf.d/*.conf
  /etc/systemd/zram-generator.conf.d/*.conf
  /run/systemd/zram-generator.conf.d/*.conf
  ```

  A file is only counted as real configuration if it actually contains
  a `[zramN]` section header — **a directory existing (even a
  `conf.d/` with only unrelated files in it) is not configuration**,
  fixing a real S2 false-positive (see
  `docs/validation/s2r/zram-validation.md`). `MemoryPolicyInfo.
  zram_generator_config_sources` lists every real source found (empty
  means genuinely unconfigured); `zram_generator_config_ambiguous` is
  `True` when more than one source exists — Serein does not attempt to
  resolve final precedence, it just treats that as "already configured,
  do not add a third layer" rather than guessing which one wins.

Nothing here ever modifies swap. `serein hardware plan`'s `memory.zram`
action is the only place a ZRAM *recommendation* appears, and it is
read-only.

## Why ZRAM, not "swap is bad"

Serein treats RAM, ZRAM, and disk-backed swap as three complementary
mechanisms, not a hierarchy where one replaces the others. Serein never
disables or removes existing disk swap.

## Sizing policy: upstream's own defaults, current syntax

`hardware/defaults/zram-generator.conf` (planning-only in S2/S2R — see
`resources.py`; never installed by this repository):

```ini
[zram0]
zram-size = min(ram / 2, 4096)
swap-priority = 100
```

- **`zram-size = min(ram / 2, 4096)`** — this is the tool's own
  documented default (`zram-generator.conf(5)`: "Defaults to
  `min(ram / 2, 4096)`"). Serein pins it explicitly for
  self-documentation and robustness against a future upstream default
  change, not because the value differs from upstream. Verified by
  actually creating a real zram device with this exact expression in a
  disposable Ubuntu 26.04 VM (`--setup-device`, since the full generator
  refuses to run under container-detected virtualization — see
  `docs/validation/s2r/zram-validation.md`) — the resulting device size
  matched the formula exactly against the VM's real RAM.
- **`compression-algorithm` is intentionally not set.** The real man
  page: "If unset, none will be configured and the kernel's default
  will be used." Serein defers to the kernel default until a real
  benchmark (`docs/hardware/planning-and-safety.md`'s benchmark
  contract) shows a measured reason to pin `zstd`, `lz4`, or any other
  algorithm.
- **`swap-priority = 100`** — also the tool's own documented default
  ("If unset, 100 is used"). Pinned here for the same
  self-documentation reason as `zram-size`, not because Serein
  overrides upstream's choice.

Resulting size by RAM tier (unchanged from S2 — the *value* was never
wrong, only the option names used to express it):

| RAM tier | `RAM / 2` | Capped at 4096 MiB | Resulting ZRAM | As % of RAM |
|---|---|---|---|---|
| ≤ 8 GiB | ≤ 4096 MiB | no cap needed | up to 4 GiB | up to 50% |
| 16 GiB | 8192 MiB | capped | 4 GiB | 25% |
| 32 GiB | 16384 MiB | capped | 4 GiB | 12.5% |
| 64+ GiB | 32768+ MiB | capped | 4 GiB | ≤ 6.25% |

## An important finding: installing the package alone may be sufficient

Live validation found that Ubuntu 26.04's `systemd-zram-generator`
package ships its own default config at `/usr/lib/systemd/
zram-generator.conf` containing a bare `[zram0]` section — which, per
the documented defaults above, **already produces exactly Serein's
intended policy with zero additional configuration**. Serein's own
drop-in (a future `/etc/systemd/zram-generator.conf.d/90-serein.conf`)
therefore exists mainly for:

1. Self-documentation — Serein's intended policy is explicit and
   readable, not silently inherited from whatever upstream's default
   happens to be today.
2. Robustness against a future upstream default change.
3. Establishing the mechanism for a later, deliberate divergence (e.g.
   the `ai` profile eventually wanting a different ratio), without
   relying on implicit inheritance.

This is recorded as a genuine, positive finding, not a reason to change
the plan's behavior — see `docs/validation/s2r/zram-validation.md`.

## Conflict avoidance

`planner._zram_action()` checks, in order: an existing active `/sys/
block/zram*` device (strongest evidence) → any real config source found
above → whether the current environment is WSL/a container (see below)
→ RAM size availability → whether ZRAM support itself is proven (see
below). If either of the first two is present, the action is `NOOP`,
explicitly stating Serein will not layer a second, competing
implementation. `serein hardware doctor`'s `hardware_existing_zram`
check mirrors this: `PASS` if found, `WARN` if ambiguous (multiple
sources), `SKIP` if genuinely unconfigured — never `FAIL` for simply
not having ZRAM yet.

## Capability-gated planning (S2R micro-corrective)

**ZRAM planning is capability-gated: Serein does not propose
configuration unless kernel support is positively detected.**
`memory_policy.detect_zram_capability()` is the single shared function
both `serein hardware capabilities` (`zram_configurable`) and
`serein hardware plan`'s `memory.zram` action call — the same evidence
(`/sys/class/zram-control`, a loaded `zram` module, or an existing
device), the same virtualization guard, one source of truth. A bare-metal
host with RAM known, no existing implementation, and no proof of kernel
ZRAM support now correctly reports `memory.zram = BLOCKED` (*"ZRAM
support could not be confirmed on this host..."*), not `APPLY` — fixing
a real inconsistency where the planner could previously propose `APPLY`
for a machine the capability model had already said couldn't support it.
See `docs/validation/s2r/zram-validation.md`.

## Virtualization: a verified, not assumed, guard

Live validation found that `systemd-zram-generator`'s own generator
**refuses to create any device when `systemd-detect-virt --container`
reports a container context** — which includes WSL2 (`systemd-detect-virt`
identifies it as `"wsl"`). This was observed directly: running the real
generator inside a disposable Ubuntu 26.04 WSL2 instance printed
`"Running in a container, exiting."` and produced no output, while the
same config parsed and created a real device successfully via the
lower-level `--setup-device` path. Serein's `zram_configurable`
capability and the planner's `memory.zram` action both report
unavailable/`SKIP` under WSL/containers on this **verified**, not
guessed, basis (see `docs/validation/s2r/zram-validation.md`).

## Swappiness

S2/S2R make **no swappiness recommendation of any kind** — neither a
global change nor a profile-specific one. No measurement exists yet to
justify a specific value over the kernel default.
