"""Whonix Gateway/Workstation capability detection.

Whonix is always modeled as two components - Gateway and Workstation -
never a single generic VM (Section 25). Reuses S5's
``detect_vm_status``/``evaluate_vm_readiness`` directly (Section 27) -
no second KVM/QEMU/libvirt detector exists here.

Image presence is checked only at the exact path the official Whonix
KVM documentation names as the install target -
``~/.local/share/images/Whonix-{Gateway,Workstation}.qcow2`` - never a
filesystem-wide search (Section 29). A matching filename at that exact
path is still not treated as a verified, genuine Whonix image (Section
31): real verification requires the signature/hash check Whonix's own
docs describe, which S6 never performs (no download happens here
either - Section 30).
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.virtualization import detect_vm_status, evaluate_vm_readiness
from serein.development._util import default_home, marker_exists
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.veil.models import WhonixCapabilityInfo

_IMAGE_DIR = (".local", "share", "images")
_GATEWAY_IMAGE = "Whonix-Gateway.qcow2"
_WORKSTATION_IMAGE = "Whonix-Workstation.qcow2"


def detect_whonix_status(
    runner: CommandRunner = DEFAULT_RUNNER,
    root: Path = DEFAULT_ROOT,
    home: Path | None = None,
) -> WhonixCapabilityInfo:
    if home is None:
        home = default_home()

    vm = detect_vm_status(runner=runner, root=root)
    readiness = evaluate_vm_readiness(vm)
    gateway_present = marker_exists(home, *_IMAGE_DIR, _GATEWAY_IMAGE)
    workstation_present = marker_exists(home, *_IMAGE_DIR, _WORKSTATION_IMAGE)

    if readiness.status != "ready":
        return WhonixCapabilityInfo(
            vm_readiness=readiness,
            gateway_image_present=gateway_present,
            workstation_image_present=workstation_present,
            network_topology_configured=False,
            usable=False,
            confidence="high" if readiness.status == "blocked_no_hardware" else "medium",
            reason="VM backend is not ready (" + readiness.status + "): "
            + readiness.reason + " Whonix requires a usable KVM+QEMU+"
            "libvirt VM backend before Gateway/Workstation images even "
            "matter.",
        )
    if not (gateway_present and workstation_present):
        missing = [
            name for name, present in (
                ("Gateway", gateway_present), ("Workstation", workstation_present),
            ) if not present
        ]
        return WhonixCapabilityInfo(
            vm_readiness=readiness,
            gateway_image_present=gateway_present,
            workstation_image_present=workstation_present,
            network_topology_configured=False,
            usable=False,
            confidence="medium",
            reason="VM backend is ready, but the following Whonix image(s) "
            f"are not present at the expected location: {', '.join(missing)}. "
            "Serein never downloads a Whonix image (Section 30) - see "
            "docs/veil/whonix.md for the official source/verification "
            "procedure.",
        )
    return WhonixCapabilityInfo(
        vm_readiness=readiness,
        gateway_image_present=True,
        workstation_image_present=True,
        network_topology_configured=False,
        usable=None,
        confidence="low",
        reason="VM backend is ready and both Gateway/Workstation images are "
        "present at the expected location, but Serein never verified "
        "their signature/hash, never imported them (no 'virsh define'), "
        "and never configured the required internal-network topology "
        "(Section 31-33) - usability stays unknown, never assumed true "
        "from filename presence alone.",
    )
