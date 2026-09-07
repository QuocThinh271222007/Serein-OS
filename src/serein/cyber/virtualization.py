"""VM/KVM capability detection.

Every signal here is read-only (Section 34): a filesystem existence
check for ``/dev/kvm``, a ``/proc/modules`` scan for the ``kvm``
kernel module (mirroring S2's own ``_kernel_module_loaded`` pattern
for GPU kernel modules — same evidence class, not re-implemented from
a different design), and plain ``--version``-style binary probes for
``qemu-system-x86_64``/``virsh``. Never starts ``libvirtd``, never
creates a VM, never modifies groups. "VM usable" is never inferred
from one binary alone (Section 35) — ``VMCapabilityInfo`` keeps
device presence, kernel module state, both binaries, and user access
as separate fields.

``evaluate_vm_readiness()`` is the single canonical function that turns
those independent fields into one readiness verdict (S5R corrective
Section 17-18) — ``capabilities.py``, ``planner.py``, and ``doctor.py``
all call this instead of each deriving "is a VM usable" separately,
which had previously let the capability and the planner disagree about
whether libvirt was required. Canonical managed stack: KVM + QEMU +
libvirt.
"""

from __future__ import annotations

import os
from pathlib import Path

from serein.cyber.models import VMCapabilityInfo, VMReadiness
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware._util import DEFAULT_ROOT, read_text


def _kvm_device_present(root: Path) -> bool:
    return (root / "dev" / "kvm").exists()


def _kvm_module_loaded(root: Path) -> bool:
    modules_text = read_text(root / "proc" / "modules")
    if modules_text:
        for line in modules_text.splitlines():
            fields = line.split()
            if fields and fields[0] in ("kvm", "kvm_intel", "kvm_amd"):
                return True
    return (root / "sys" / "module" / "kvm").is_dir()


def _kvm_user_access(root: Path, kvm_present: bool) -> bool | None:
    """A real, read-only filesystem permission check
    (``os.access(..., R_OK | W_OK)``) — never opens or otherwise uses
    the device. None when the device doesn't exist or the check itself
    fails (e.g. no such concept on this platform)."""
    if not kvm_present:
        return None
    kvm_path = root / "dev" / "kvm"
    try:
        return os.access(kvm_path, os.R_OK | os.W_OK)
    except OSError:
        return None


def detect_vm_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> VMCapabilityInfo:
    kvm_present = _kvm_device_present(root)
    return VMCapabilityInfo(
        kvm_device_present=kvm_present,
        kvm_module_loaded=_kvm_module_loaded(root),
        qemu=probe_tool("qemu-system-x86_64", "qemu-system-x86_64", runner=runner),
        libvirt=probe_tool("virsh", "virsh", version_args=("--version",), runner=runner),
        user_access=_kvm_user_access(root, kvm_present),
    )


def evaluate_vm_readiness(vm: VMCapabilityInfo) -> VMReadiness:
    """The single canonical VM-readiness verdict (S5R Section 17-18).
    Checked in a fixed order, each a hard requirement for the next -
    ``usable`` is ``True`` only for the final ``"ready"`` status, and
    ``user_access is None`` is always treated as not-ready (Section 20:
    unknown is never guessed true)."""
    if not vm.kvm_device_present:
        return VMReadiness(
            False, vm.user_access, vm.qemu.installed, vm.libvirt.installed, False,
            "blocked_no_hardware",
            "/dev/kvm is not present - hardware virtualization is "
            "unavailable or not exposed to this environment.",
        )
    if not vm.kvm_module_loaded:
        return VMReadiness(
            True, vm.user_access, vm.qemu.installed, vm.libvirt.installed, False,
            "blocked_module_missing",
            "/dev/kvm exists but the kvm kernel module is not loaded.",
        )
    if vm.user_access is None:
        return VMReadiness(
            True, None, vm.qemu.installed, vm.libvirt.installed, False,
            "blocked_access_unknown",
            "Whether the current user can access /dev/kvm could not be "
            "determined - treated as not-ready, never guessed true.",
        )
    if vm.user_access is False:
        return VMReadiness(
            True, False, vm.qemu.installed, vm.libvirt.installed, False,
            "blocked_no_access",
            "/dev/kvm is present but the current user cannot read/write it - "
            "this requires explicit future user/admin action (e.g. kvm "
            "group membership); Serein never modifies group membership "
            "automatically.",
        )
    if not vm.qemu.installed:
        return VMReadiness(
            True, True, False, vm.libvirt.installed, False, "needs_qemu",
            "Hardware virtualization and device access are ready; qemu is "
            "not yet installed.",
        )
    if not vm.libvirt.installed:
        return VMReadiness(
            True, True, True, False, False, "needs_libvirt",
            "Hardware virtualization, device access, and qemu are ready; "
            "libvirt is not yet installed.",
        )
    return VMReadiness(
        True, True, True, True, True, "ready",
        "KVM device, kernel module, user access, qemu, and libvirt are all "
        "confirmed present.",
    )
