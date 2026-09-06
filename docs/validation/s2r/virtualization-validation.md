# S2R — Virtualization Guard Revalidation

## WSL

Confirmed live (see `zram-validation.md`) that `systemd-zram-generator`'s
own generator declines to run under WSL2 (`systemd-detect-virt`
identifies it as a `"wsl"` container context). This directly validates
Serein's own WSL guard for the new `zram_configurable` capability and
the `memory.zram` plan action — Serein's guard now matches *verified*
upstream tool behavior, not merely a Serein-side assumption.

`cpufreq` and `queue/scheduler` sysfs are both confirmed absent under
WSL2 (see `cpu-validation.md`, `storage-validation.md`), independently
confirming those existing guards are exercised on real absence, not
just fixture simulation.

```
S2R_WSL_GUARDS_VALIDATED=true
```

## Container

Not independently re-validated live in S2R (no container runtime was
exercised inside the disposable VM beyond `systemd-detect-virt`'s own
generic container detection, which WSL2 itself satisfies). The
container guard logic is identical code path to the WSL guard
(`_virtualized()` checks `environment.is_container` alongside
`virtualization == "wsl"`), and S2's original container-detection tests
(`.dockerenv`, cgroup markers) are unchanged and still pass.

```
S2R_CONTAINER_GUARDS_VALIDATED=PARTIAL   (code path shared with the WSL guard, which was verified; container-specific detection itself not independently re-run against a real container runtime in S2R)
```

## VM (not blanket-guarded)

Unchanged from S2: a bare VM (KVM/VMware/VirtualBox/Hyper-V) is **not**
forced to SKIP CPU/storage/ZRAM actions the way WSL/containers are —
`_virtualized()` only checks for `"wsl"` and `is_container`, never
generic hypervisor detection. `kvm_vm` fixture tests confirm a VM's
real (or absent) sysfs interfaces are read and reasoned about normally,
per Section 37 of the S2R brief: "Do not blanket-disable guest-controlled
mechanisms."
