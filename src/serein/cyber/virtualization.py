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
as separate fields; callers decide what combination means "ready".
"""

from __future__ import annotations

import os
from pathlib import Path

from serein.cyber.models import VMCapabilityInfo
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
