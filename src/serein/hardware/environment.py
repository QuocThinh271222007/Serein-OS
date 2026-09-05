"""Virtualization / container / WSL context detection.

Heuristics, in priority order:

1. WSL — ``/proc/version`` (or ``/proc/sys/kernel/osrelease``) contains
   "microsoft", the marker WSL's kernel build has carried since WSL1.
2. Container — ``/.dockerenv`` exists, or ``/proc/1/cgroup`` mentions a
   known container runtime. This is not exhaustive (podman rootless setups
   vary) but covers the common cases without requiring root.
3. Hypervisor DMI strings — ``/sys/class/dmi/id/{sys_vendor,product_name}``
   naming a known VM vendor (QEMU/KVM, VMware, VirtualBox, Hyper-V, Xen).
4. ``hypervisor`` CPU flag in ``/proc/cpuinfo`` as a last-resort signal that
   *something* virtualizes this CPU, without knowing what.

Anything else is reported as "none". This must never be read as a security
boundary check — it is descriptive, for `serein status`/`doctor` context only.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import EnvironmentInfo

_DMI_VENDOR_MARKERS = {
    "qemu": "kvm",
    "kvm": "kvm",
    "vmware": "vmware",
    "virtualbox": "virtualbox",
    "microsoft corporation": "hyperv",
    "xen": "xen",
}


def _is_wsl(root: Path) -> bool:
    for rel in ("proc/version", "proc/sys/kernel/osrelease"):
        text = read_text(root / rel)
        if text and "microsoft" in text.lower():
            return True
    return False


def _is_container(root: Path) -> bool:
    if (root / ".dockerenv").exists():
        return True
    cgroup = read_text(root / "proc" / "1" / "cgroup")
    if cgroup:
        lowered = cgroup.lower()
        if any(marker in lowered for marker in ("docker", "kubepods", "containerd", "lxc")):
            return True
    return False


def _dmi_virtualization(root: Path) -> str | None:
    dmi_dir = root / "sys" / "class" / "dmi" / "id"
    for filename in ("sys_vendor", "product_name"):
        text = read_text(dmi_dir / filename)
        if not text:
            continue
        lowered = text.strip().lower()
        for marker, label in _DMI_VENDOR_MARKERS.items():
            if marker in lowered:
                return label
    return None


def _has_hypervisor_flag(root: Path) -> bool:
    text = read_text(root / "proc" / "cpuinfo")
    if not text:
        return False
    return "hypervisor" in text


def detect_environment(root: Path) -> EnvironmentInfo:
    is_wsl = _is_wsl(root)
    is_container = _is_container(root)

    if is_wsl:
        virtualization = "wsl"
    elif is_container:
        virtualization = "container"
    else:
        virtualization = _dmi_virtualization(root) or (
            "unknown-hypervisor" if _has_hypervisor_flag(root) else "none"
        )

    return EnvironmentInfo(
        virtualization=virtualization,
        is_wsl=is_wsl,
        is_container=is_container,
    )
