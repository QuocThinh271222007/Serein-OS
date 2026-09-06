# Planning Model, Config Ownership, and Safety Rules

## The plan action shape

Every `PlanAction` (`src/serein/hardware/models.py`) carries all of:

```
id, component, action, target, current, reason,
confidence, requires_root, reversible, risk, verification, status
```

`status` is always one of `APPLY` / `NOOP` / `SKIP` / `BLOCKED` —
never a bare boolean, and never silently omitted. `reason` is always a
plain-English justification, not a code. Plans are deterministic: calling
`build_hardware_plan(profile_id, root)` twice against the same `root`
produces byte-identical output (`tests/test_hardware_policy.py::
TestPlanner::test_deterministic`).

## Config ownership: real files, planning-only in S2

`hardware/defaults/zram-generator.conf` (repo root — planning data,
listed in `src/serein/hardware/resources.py`, distinct from the
`src/serein/hardware/` *code* package) is the one concrete config
artifact S2 ships. It targets `/etc/systemd/zram-generator.conf.d/
90-serein.conf` — a `.conf.d` drop-in, never `/etc/systemd/
zram-generator.conf` itself, so a future Apply step would never overwrite
anything the `systemd-zram-generator` package itself owns. This mirrors
the exact discipline S1R established and verified for the desktop layer's
`/etc/xdg` drop-ins: own an unclaimed, additive path; never touch a
package-owned file.

**Collision risk has not been re-verified against a live Ubuntu 26.04
archive for this specific path in S2** (S1R's `dpkg-query -S` methodology
would be the way to do it) — recorded honestly in
`docs/hardware/known-limitations.md` rather than assumed clean by
analogy alone.

Other potential target classes named in the S2 brief
(`/etc/sysctl.d/`, `/etc/udev/rules.d/`, `/etc/systemd/system/`) have **no
artifact and no target path chosen in S2** — S2 makes no swappiness,
udev, or systemd-unit proposal at all (see `memory-policy.md`'s
swappiness section), so there is nothing to own there yet.

## Reversibility

| Action class | Reversibility |
|---|---|
| CPU EPP (`cpu.epp`) | Reversible — a single sysfs write, takes effect immediately, no reboot. |
| Power profile (`power.ppd_profile`) | Reversible — `powerprofilesctl set <profile>`. |
| ZRAM (`memory.zram`) | Reversible after a service reload/reboot — removing the `.conf.d` drop-in and restarting `systemd-zram-setup@zram0` (or rebooting) fully reverts to no ZRAM. |
| Storage scheduler (`storage.scheduler.<dev>`) | Reversible — a single sysfs write, no reboot. |

Every `PlanAction` in S2 reports `reversible: true`. There is currently no
action in any default Serein profile that is irreversible or high-risk —
by design (see Forbidden Optimizations below), not by omission.

## Risk model

```
none   — informational only, or already at the target state
low    — a single, well-understood, reversible sysfs/service write
medium — (unused in S2; reserved for future Apply-stage actions with
          a larger blast radius, e.g. multi-file config changes)
high   — (unused in S2; reserved, and any future high-risk action would
          need its own explicit justification and opt-in, never a default)
```

No S2 profile plan contains a `medium` or `high` risk action. This is a
direct, intentional consequence of Section 65 of the S2 brief: "Serein
defaults should generally contain none/low. High-risk actions should not
exist in default S2 profiles."

## Forbidden optimizations (never, at any phase, without a dedicated,
explicitly-justified redesign)

Disabling thermal throttling or CPU mitigations, disabling AppArmor or
ASLR, disabling watchdogs, raising GPU power limits, GPU/CPU voltage
changes, fan firmware hacks, EC writes, unsafe MSR writes, arbitrary
kernel boot parameters, and overclocking of any kind. None of these
appear anywhere in `planner.py`, and none are planned for any named
future phase either — Serein is a workstation platform, not a
benchmark/overclocking distribution.

## Benchmark contract (design only — no benchmarks run in S2)

A tuning change must eventually show a **measured** improvement before it
can become a Serein default — this is the literal meaning of "Measure" in
Integrate → Measure → Replace, and S2 deliberately does not skip ahead of
it. The metrics a future measurement pass should use, once real
before/after comparison is warranted:

```
idle RAM usage             idle CPU residency (C-state distribution)
compile-workload duration  memory-pressure/reclaim behavior
swap/ZRAM hit-and-fault rates          disk read/write latency
power draw (where a wattmeter/RAPL interface is available)
thermal stability under sustained load
AI throughput (tokens/sec, batches/sec) — once S4 exists to measure it
```

No synthetic benchmark harness is implemented in S2 — building one before
there's a tuning change worth measuring would be premature. This section
exists so a future phase has an agreed contract to hold new defaults to,
rather than inventing benchmark criteria ad hoc when the question
eventually comes up.
