# Whonix Gateway/Workstation Model

## Two VMs, never one generic VM (Section 25)

Whonix is always Gateway + Workstation, never modeled as a single VM.
The strong-isolation flow is:

```
Workstation VM -> internal isolated virtual network -> Gateway VM -> Tor -> Internet
```

`WhonixCapabilityInfo` (`src/serein/veil/models.py`) keeps
`gateway_image_present`/`workstation_image_present` as independent
fields for exactly this reason - a complete pair is required before
anything about "Whonix usable" can even be considered.

## Reuses S5's VM readiness directly (Section 27)

`whonix.py`'s `detect_whonix_status()` calls
`serein.cyber.virtualization.detect_vm_status`/`evaluate_vm_readiness`
- the exact same `VMReadiness` verdict S5's `vm_isolation` capability
and `vm.prerequisites` plan action use. No second KVM/QEMU/libvirt
detector exists in this codebase. The canonical managed stack stays
KVM + QEMU + libvirt, checked in the same fixed order S5R established:
device present -> module loaded -> user access known and granted ->
qemu installed -> libvirt installed -> `"ready"`.

## Official distribution model (verified 2026-09)

Live research against `whonix.org/wiki/KVM` confirms the current
official KVM install approach: separate `.libvirt.xz` archives per
component (Gateway, Workstation), each containing a qcow2 disk image
and a libvirt XML template; the documented install workflow explicitly
tells users to move/copy the extracted qcow2 files to
`~/.local/share/images/` before running `virsh define` on the XML
templates. OpenPGP and signify signatures are both offered for
verification.

## Image presence detection (Section 29, no filesystem-wide search)

`detect_whonix_status()` checks *only* the two exact, documented
official install paths:

```
~/.local/share/images/Whonix-Gateway.qcow2
~/.local/share/images/Whonix-Workstation.qcow2
```

via `serein.development._util.marker_exists` (the same injectable-home
helper S3's `python.py`/`node.py` use for `.pyenv`/`.nvm` markers) -
never a recursive or wildcard scan of the user's home directory. A
differently-named file at that path, or a correctly-named file
anywhere else, is never detected
(`tests/test_veil.py::TestWhonix::test_never_scans_home_directory_wide`).

## A matching filename is never "verified" (Section 31)

Even when both images are present at the expected path,
`WhonixCapabilityInfo.usable` stays `None`, never `True`
(`tests/test_veil.py::TestWhonix::test_both_images_present_topology_unproven`)
- Serein never checks the OpenPGP/signify signature, never verifies a
hash, and never imports the image (`virsh define`). Real verification
requires the exact procedure Whonix's own documentation describes,
which a future phase would need to implement explicitly; trusting a
file because its name matches `Whonix-Gateway.qcow2` is exactly the
anti-pattern Section 31 calls out.

## No download, ever (Section 30)

No `wget`/`curl`/torrent/`virsh` VM-import call exists anywhere in this
subsystem - confirmed by regression
(`tests/test_veil.py::TestWhonix::test_never_creates_or_imports_a_vm`,
and the workflow-wide `test_full_workflow_never_issues_a_mutating_or_network_command`).

## Direct clearnet egress invariant (Section 32-33/100, ADR-0024)

The canonical topology requires Whonix-Workstation to have **no**
direct clearnet-facing network adapter - it must route exclusively
through Whonix-Gateway's internal-only network, which itself NATs out
through the host. `planner.py`'s `whonix.network_topology` action
encodes this invariant directly in its `tool`/`reason` text ("internal-
only Whonix-Workstation adapter (never direct clearnet egress)"), and
a dedicated regression
(`tests/test_veil.py::TestInvariants::test_whonix_workstation_never_planned_with_direct_clearnet_egress`)
asserts the invariant statement is present and no bridged/direct-egress
phrasing ever appears, regardless of what a future Apply engine
eventually implements.

## Minimal host integration for the Gateway/profile (Section 34-36)

Documented trade-off, not yet enforced by any Apply mechanism: a
Whonix/private-workspace profile should default to no shared folders,
no host clipboard integration, and no SPICE file sharing/USB
passthrough - home-directory mounts into a privacy VM are explicitly
the wrong default. This is a policy Serein documents now so a future
provisioning phase does not have to relitigate it.
