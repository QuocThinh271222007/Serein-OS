# S5 Known Limitations

Honest accounting of what S5 does and does not prove, matching S1R/S2R/
S3R/S4's own precedent of documenting scope rather than overstating it.

## No production Apply engine

`serein cyber plan` describes; it never executes. No package, container,
VM, firewall rule, or capture-privilege change is ever performed by
this codebase. A real Apply engine (S7/S8-adjacent, not scheduled)
would need privilege-escalation handling, a per-action rollback
strategy, and — critically for this domain — an explicit, separately-
authorized step before ever touching capture privileges, container
privileges, or VM creation.

## Real capture-privilege denial could not be reproduced

The disposable WSL2 validation environment's default capability model
is more permissive toward raw-socket-adjacent operations than a real
multi-user Ubuntu desktop session: an unprivileged test user's
`dumpcap -D` succeeded there despite no group membership or file
capability being granted. The tri-state permission logic itself
(`True`/`False`/`None`) is exhaustively unit-tested against all three
real `dumpcap -D` outcomes; only the "denied" branch's real-world
trigger condition could not be reproduced live. See
`docs/validation/s5/known-blockers.md`.

## No real KVM nested-virtualization or wireless-hardware evidence

`/dev/kvm` is not exposed inside this session's WSL2 environment, and
no wireless interface is exposed either. `qemu`/`libvirt`/`aircrack-ng`
package existence was confirmed live; the runtime capability fields
(`kvm_device_present`, `kvm_module_loaded`, `user_access`, wireless
monitor-mode capability) are exercised exclusively via fake-root-tree
and `FakeCommandRunner` unit tests, never real hardware.

## WSL limitations for the tooling itself

Some Host Cyber Light tooling works fully under WSL (CLI diagnostics,
`nmap`/`tcpdump`/`tshark` presence and version detection, `openssl`,
web-testing CLI tools, RE tooling); some fundamentally cannot function
the same way under WSL regardless of what Serein detects: raw host
packet capture on a genuine host NIC, wireless monitor mode, KVM nested
virtualization, and real Linux NIC-level access all depend on
capability WSL2's virtualized environment does not provide the same way
a bare-metal Ubuntu installation would. Serein does not claim full
capability in these cases — `capabilities.py`'s `usable` fields degrade
to `None`/`False` rather than assuming success.

## `dnsutils` package rename (Ubuntu 26.04)

Documented at length in `docs/validation/s5/package-validation.md`
Finding 1: the transitional `dnsutils` package no longer exists on
Ubuntu 26.04. Fixed to `bind9-dnsutils` throughout `tools.py`,
`planner.py`, `capabilities.py`, and the profile manifest — this is
exactly the kind of "surprising difference" earlier phases (S3's
`p7zip-full`→`7zip`, `fd-find`/`bat` binary names) already established
a precedent for recording rather than silently carrying forward a stale
assumption.

## `qemu-system-x86_64`/`libvirt` are binary names, not package names

A second real correction from the same validation pass: `virtualization.py`'s
tool *probes* were already correct (the binaries genuinely exist once
the right packages are installed), but the VM planner had briefly named
the binaries themselves as the packages to install. Fixed to
`qemu-system-x86, libvirt-daemon-system, libvirt-clients` — see
`docs/validation/s5/package-validation.md` Finding 4.

## Live validation is Tier B (package/metadata/default-privilege-state only)

Matching every prior phase's own definition: real `apt`/`dpkg`
package-archive access, a real combined dependency-closure simulation,
and one real (non-interactive) `apt install tshark` to observe
`dumpcap`'s genuine default on-disk privilege state, all in a
disposable Ubuntu 26.04 WSL2 instance (`docs/validation/s5/`). This is
**not**: real capture-denial runtime evidence, real KVM
nested-virtualization evidence, real wireless-hardware evidence, or
proof that Distrobox's image-creation flow or any VM-creation workflow
succeeds end-to-end — none of the latter were ever going to be
exercised regardless of environment availability, since S5 has no
Apply engine.

## No Kali repository was added at any point

The validation environment never had a Kali apt source configured —
S5 does not target Kali as a host or default toolbox base image, so
there was nothing to validate there. A future, explicitly-optional Kali
toolbox path (Section 30) is documented as a possibility, not
implemented or validated in this phase.
