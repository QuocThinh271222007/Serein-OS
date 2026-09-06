# S5 — Known Blockers

What remains unverified after this pass, and why none of it blocks the
corrections/implementation made.

## No real packet-capture privilege evidence

```
LIVE_PACKET_CAPTURE_VALIDATION=PARTIAL
```

The disposable Ubuntu 26.04 WSL2 instance let a real, non-interactive
`apt-get install -y tshark` run to completion and confirmed `dumpcap`'s
default on-disk state (owned by `wireshark-common`, no file
capabilities set, no `wireshark` group created — see
`package-validation.md` Finding 3). That is genuine evidence for the
*installed-but-unprivileged* state.

It could **not** validate the *denied* code path realistically: a
freshly created unprivileged user inside this WSL2 instance ran
`dumpcap -D` and it **succeeded** (listed `eth0`, `lo`, and other
interfaces) despite no group membership and no file capability being
granted:

```
$ su testuser -c 'dumpcap -D'
1. eth0
2. any
3. lo (Loopback)
...
RC=0
```

WSL2's default namespace/capability model is more permissive toward
raw-socket-adjacent operations than a real multi-user Ubuntu desktop
session would be — this is a genuine environmental difference, not a
Serein detection bug. `serein.cyber.capture`'s `_check_capture_permission`
was exercised primarily via `FakeCommandRunner`-driven unit tests
(`tests/test_cyber.py::TestCapture`) with canned `dumpcap -D`
returncode-0/nonzero/absent scenarios covering all three real outcomes
(`True`/`False`/`None`) — the *logic* is fully tested; only the "denied"
branch's real-world trigger condition (a genuinely restrictive
multi-user Linux session) could not be reproduced in this environment.
The test user and its home directory were removed before the
disposable instance was unregistered.

## No real KVM nested-virtualization evidence

```
LIVE_KVM_VALIDATION=BLOCKED
```

WSL2 does not expose `/dev/kvm` to its Linux environment by default
(and this dev host's WSL2 instance had none present), so
`detect_vm_status`'s `kvm_device_present`/`kvm_module_loaded`/
`user_access` fields were exercised exclusively via `tmp_path`-based
fake root trees in `tests/test_cyber.py::TestVM`, not a real device.
`qemu`/`libvirt` **package existence** and dependency-closure resolution
were confirmed live (see `package-validation.md` Finding 4); actual VM
boot/nested-virtualization behavior was not, and could not be, exercised
— consistent with S5 never creating a VM in the first place.

## No real wireless-hardware evidence

```
LIVE_WIRELESS_VALIDATION=BLOCKED
```

No wireless network interface is exposed to the WSL2 validation
environment. `aircrack-ng`'s package existence was confirmed live;
monitor-mode capability, hardware-driver support, and any actual
wireless-tooling behavior remain untested by design — Section 17
requires this to be modeled as capability/requirement information only,
never asserted, and `capabilities.py`'s `wireless_tooling.usable` is
unit-tested to never be inferred `True` regardless of tool presence.

## Why none of this blocks the S5 corrections

Every correction made this pass (`bind9-dnsutils` package rename,
`wireshark`-vs-`tshark` dependency-weight host-default decision,
`qemu-system-x86`/`libvirt-daemon-system`/`libvirt-clients` package-name
fix) is a package-existence/dependency-closure fact, independently
verifiable via `apt`/`dpkg` without root-restricted capture privilege,
real KVM hardware, or real wireless hardware — and each was verified
live. The privilege/capability *logic* itself (three-state capture
permission, five-independent-signal VM usability, presence-only
wireless capability) is unit-tested against realistic evidence shapes,
which is the correct scope for a Tier B validation pass; a bare-metal
Linux desktop with real capture-group semantics, real `/dev/kvm`, and
real wireless hardware would let a future pass confirm the exact
runtime boundary, not the detection logic itself.

## No live provisioning proof

Same limitation every prior phase already documented for its own
domain: this pass proves package/metadata/privilege-default facts,
never that Distrobox's own image-creation flow, Podman's own pull
mechanics, or a real VM's boot process actually completes successfully
— S5 has no Apply engine, so none of these were ever going to be
executed regardless of environment availability.
