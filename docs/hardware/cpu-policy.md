# CPU Policy

## What is detected

`src/serein/hardware/cpu_policy.py` reads `cpu0`'s `cpufreq` sysfs
directory only (`/sys/devices/system/cpu/cpu0/cpufreq/`):

- `scaling_driver` — e.g. `amd-pstate-epp`, `intel_pstate`, `acpi-cpufreq`
- `scaling_governor` / `scaling_available_governors`
- `energy_performance_preference` / `energy_performance_available_preferences`

Per-core heterogeneity (e.g. Intel P/E-core-specific policy) is out of
scope for S2 — `cpu0` is treated as representative of the system. Absence
of the whole directory (most VMs, WSL, containers, or a CPU/kernel with no
cpufreq support) is a normal `cpufreq_present=False` state, never an error.

## Why "performance governor everywhere" is rejected

1. **It's not how modern drivers work.** Both `intel_pstate` in *active*
   mode and `amd_pstate_epp` typically expose only two governors —
   `performance` and `powersave` — with the actual energy/performance
   trade-off controlled by the separate `energy_performance_preference`
   (EPP) knob, not the governor. Forcing `performance` as the *governor*
   on these drivers removes HWP's own dynamic scaling rather than biasing
   it — the opposite of what a "performance profile" should do.
2. **It ignores the active/passive P-state distinction.** `intel_pstate`
   running in *passive* mode behaves like a traditional cpufreq driver
   (schedutil et al. apply normally); forcing a fixed governor without
   checking which mode is active risks a policy that doesn't mean what it
   looks like it means. S2 does not need to distinguish active/passive
   explicitly because it never touches the governor at all (see below) —
   but a future phase that does must check this first.
3. **A developer or researcher is not a benchmark.** Section 12/15 of the
   S2 brief: a dev machine is idle-reading-code as often as it's
   compiling; a permanent `performance` governor burns power and heat for
   no measured benefit during the idle majority.

## What Serein actually proposes: EPP, never the governor

`planner.py`'s `cpu.epp` action only ever proposes a value for
`energy_performance_preference` — never `scaling_governor`. This is
deliberate: EPP is the modern, driver-agnostic, low-risk knob (reversible,
no re-scan needed, doesn't fight HWP), while the governor is a coarser,
higher-blast-radius setting Serein has no evidence-backed reason to touch.

### Candidate EPP values per profile

| Profile | Candidates (first available wins) | Why |
|---|---|---|
| `balanced` | `balance_performance`, `default`, `balance_power` | Upstream-ish default; slight nudge toward responsiveness. |
| `dev` | `balance_performance`, `default` | Sustained mixed workload — not permanently pinned. |
| `cyber` | `balance_performance`, `default` | Same reasoning as `dev` — stable VM/container responsiveness, not peak compute. |
| `ai` | `performance`, `balance_performance` if AC/desktop; else `balance_performance` | The one profile with a real performance bias — but only when not visibly battery-constrained. |
| `battery` | `balance_power`, `power` | Only reached if a battery exists at all (see `power-policy.md`). |

If none of a profile's candidates appear in this CPU's own
`energy_performance_available_preferences`, the action is `BLOCKED` (not
silently downgraded to something else) — the exact available list is
included in the reason so a human can judge the mismatch.

## Virtualization guard

Under WSL or a container, the `cpu.epp` action always reports `SKIP` with
an explicit reason, regardless of whether a stray `cpufreq` sysfs entry
happens to be readable — CPU energy policy belongs to the host in both
cases, and Serein does not claim control it does not have
(`docs/hardware/planning-and-safety.md`).
