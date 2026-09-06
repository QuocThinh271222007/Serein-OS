# VM Isolation Boundary

## "VM usable" is never inferred from one binary

`VMCapabilityInfo` (`src/serein/cyber/models.py`) keeps five
independent signals:

```python
kvm_device_present: bool     # /dev/kvm exists (filesystem check only)
kvm_module_loaded: bool      # /proc/modules or /sys/module/kvm fallback
qemu: ToolStatus             # qemu-system-x86_64 --version
libvirt: ToolStatus          # virsh --version
user_access: bool | None     # real os.access(R_OK|W_OK) on /dev/kvm
```

`virtualization.evaluate_vm_readiness(vm) -> VMReadiness` is the single
canonical function that turns those five fields into one readiness
verdict — `capabilities.py`'s `vm_isolation.usable`, `planner.py`'s
`vm.prerequisites` action, and `doctor.py`'s `cyber_vm_readiness` check
all consume this same result rather than each deriving "is a VM usable"
independently (S5R corrective, Section 17-18 — an earlier pass had let
the capability and the planner disagree about whether `libvirt` was
required, and let the planner treat `qemu`/`libvirt` presence as
sufficient even when `user_access` was `False` or unknown). The
canonical managed stack is **KVM + QEMU + libvirt**, checked in a fixed
order, each a hard requirement for the next:

```
kvm_device_present=False        → "blocked_no_hardware"   (usable=False)
kvm_module_loaded=False         → "blocked_module_missing" (usable=False)
user_access is None             → "blocked_access_unknown" (usable=False)
user_access is False            → "blocked_no_access"      (usable=False)
qemu not installed              → "needs_qemu"              (usable=False)
libvirt not installed           → "needs_libvirt"           (usable=False)
everything above satisfied      → "ready"                   (usable=True)
```

`user_access is None` (unknown) is always treated as not-ready — never
guessed `True` (Section 20). This makes `vm_isolation.usable == True`
imply `vm.prerequisites.status == "NOOP"` by construction, and is
unit-tested directly
(`tests/test_cyber.py::TestVMReadiness`/`TestCapabilities::test_vm_isolation_usable_requires_full_chain`
— `qemu` alone, with no KVM device, must never report `usable=True`).

## What requires a VM (never Distrobox, never a rootless container)

Full Kali environments, untrusted/malicious binaries, kernel exploit
labs, and network-isolation experiments all require a VM boundary —
container isolation, including a rootless Podman/Distrobox toolbox, is
**not** sufficient for hostile kernel/userspace samples, and Serein
never claims otherwise. This policy is represented as a concrete,
testable plan action (`vm.isolation_policy`, always `NOOP`,
`report_only`) rather than only living in prose — mirroring S4's
`voice.workload_note` `report_only` pattern — specifically so the
acceptance gate's Kali/malware-VM-policy checks are verifiable against
real plan output, not just documentation.

## Malware analysis must not occur on host or in an ordinary toolbox

An untrusted or suspected-malicious binary belongs in a disposable VM,
never the host and never the default Distrobox/Podman toolbox — a
container shares the host kernel, and hostile userspace/kernel samples
can exploit that shared surface in ways a VM's hardware-level boundary
does not permit. S5 has no mechanism to create such a VM (out of scope
— a future S7/S8 concern); it only detects and documents the
prerequisite state.

## Detected, never created

`virtualization.py` checks `/dev/kvm` existence, the `kvm`/`kvm_intel`/
`kvm_amd` kernel module (via `/proc/modules`, falling back to
`/sys/module/kvm`), `qemu-system-x86_64`/`virsh` presence, and a
read-only permission check on `/dev/kvm` — never opening or otherwise
using the device. `libvirtd` is never started, no VM is ever created,
and no user is ever added to the `kvm`/`libvirt` group.

## Prerequisite package names (live-corrected)

`planner.py`'s `_vm_prerequisites_action` plans real Ubuntu package
names — `qemu-system-x86, libvirt-daemon-system, libvirt-clients` —
not the probed *binary* names (`qemu-system-x86_64`/`virsh`), which do
not exist as apt package names on Ubuntu 26.04. See
`docs/validation/s5/package-validation.md` Finding 4 for the live
evidence behind this correction.

- **KVM device absent, module not loaded, `/dev/kvm` access denied, or
  access unknown** → `BLOCKED`. Serein will not say VM prerequisites
  "can be used" merely because packages could be installed — the user
  genuinely cannot run KVM yet, and fixing that (e.g. `kvm` group
  membership) is an explicit future user/admin action Serein never
  performs automatically.
- **Hardware and access confirmed ready, qemu/libvirt missing** →
  `APPLY` (install prerequisites only — never creates a VM, never
  downloads an ISO, never modifies groups).
- **Full chain ready (hardware, access, qemu, libvirt)** → `NOOP`.

## No ISO download, ever

S5 does not fetch a Kali ISO, compute or verify its checksum, or create
any VM. A future VM-creation feature would need to document an official
download source and signature/checksum verification mechanism first —
none of that exists yet, and none is implemented here.
