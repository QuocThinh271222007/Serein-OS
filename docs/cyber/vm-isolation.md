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

`capabilities.py`'s `vm_isolation` capability's `usable` field requires
the full AND-chain of all five (`kvm_device_present and
kvm_module_loaded and user_access is True and qemu.installed`) —
mirroring the same "don't derive independently in multiple places"
discipline S2R/S4R established for GPU/container capability
consistency. This is unit-tested
(`tests/test_cyber.py::TestCapabilities::test_vm_isolation_usable_requires_full_chain` —
`qemu` alone, with no KVM device, must never report `usable=True`).

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

- **KVM device absent** → `BLOCKED`. Serein will not plan VM
  prerequisites without hardware virtualization actually being exposed
  to the environment.
- **KVM present, qemu/libvirt missing** → `APPLY` (install
  prerequisites only — never creates a VM, never downloads an ISO,
  never modifies groups).
- **KVM present, qemu/libvirt installed** → `NOOP`.

## No ISO download, ever

S5 does not fetch a Kali ISO, compute or verify its checksum, or create
any VM. A future VM-creation feature would need to document an official
download source and signature/checksum verification mechanism first —
none of that exists yet, and none is implemented here.
