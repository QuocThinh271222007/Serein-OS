"""Whonix Gateway/Workstation capability detection.

Whonix is always modeled as two components - Gateway and Workstation -
never a single generic VM (Section 25). Reuses S5's
``detect_vm_status``/``evaluate_vm_readiness`` directly (Section 27) -
no second KVM/QEMU/libvirt detector exists here.

Image presence is checked only at the exact path the official Whonix
KVM documentation names as the install target -
``~/.local/share/images/Whonix-{Gateway,Workstation}.qcow2`` - never a
filesystem-wide search (Section 29).

**Artifact trust lifecycle (S6R Corrective D).** File presence,
signature/hash verification, libvirt domain import, and network
topology are four genuinely separate facts, never collapsed:
``ABSENT -> PRESENT_UNVERIFIED -> VERIFIED -> DEFINED -> TOPOLOGY_CONFIGURED
-> USABLE``. Serein performs none of the verification/import/topology
steps itself, so a matching filename is never treated as a verified,
genuine Whonix image (Section 31) - ``*_image_verified`` stays ``None``
(never guessed ``True`` from presence). Domain-definition state
(``*_domain_defined``) also stays ``None`` deliberately: Serein has no
safe way to strongly map a libvirt domain name to the *specific*
verified artifact it claims to represent (Section 33), so rather than
running ``virsh list`` and overclaiming from a name match, this field
is conservatively left unknown - "conservative is acceptable" per the
corrective brief. No download, verification, import, or topology
configuration happens here (Section 30/36).
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.virtualization import detect_vm_status, evaluate_vm_readiness
from serein.development._util import default_home, marker_exists
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.veil.models import WHONIX_ARTIFACT_LIFECYCLE_STAGES, WhonixCapabilityInfo

_IMAGE_DIR = (".local", "share", "images")
_GATEWAY_IMAGE = "Whonix-Gateway.qcow2"
_WORKSTATION_IMAGE = "Whonix-Workstation.qcow2"


def _artifact_lifecycle_stage(
    present: bool, verified: bool | None, domain_defined: bool | None, topology_configured: bool
) -> str:
    """One artifact's own stage in ``WHONIX_ARTIFACT_LIFECYCLE_STAGES`` -
    each stage requires the previous one to be a confirmed ``True``,
    never inferred from the next stage's absence."""
    if not present:
        return "absent"
    if verified is not True:
        return "present_unverified"
    if domain_defined is not True:
        return "verified"
    if not topology_configured:
        return "defined"
    return "topology_configured"


def _joint_stage(gateway_stage: str, workstation_stage: str) -> str:
    """The weaker of the two artifacts' stages - Whonix as a whole can
    never be further along than its least-advanced half."""
    gateway_index = WHONIX_ARTIFACT_LIFECYCLE_STAGES.index(gateway_stage)
    workstation_index = WHONIX_ARTIFACT_LIFECYCLE_STAGES.index(workstation_stage)
    return WHONIX_ARTIFACT_LIFECYCLE_STAGES[min(gateway_index, workstation_index)]


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

    # Serein performs no signature/hash verification and no libvirt
    # domain mapping - both always None, conservative by design
    # (Section 31-33), never inferred True from presence alone.
    gateway_verified: bool | None = None
    workstation_verified: bool | None = None
    gateway_defined: bool | None = None
    workstation_defined: bool | None = None

    gateway_stage = _artifact_lifecycle_stage(
        gateway_present, gateway_verified, gateway_defined, False
    )
    workstation_stage = _artifact_lifecycle_stage(
        workstation_present, workstation_verified, workstation_defined, False
    )
    lifecycle_stage = _joint_stage(gateway_stage, workstation_stage)

    if readiness.status != "ready":
        return WhonixCapabilityInfo(
            vm_readiness=readiness,
            gateway_image_present=gateway_present,
            workstation_image_present=workstation_present,
            gateway_image_verified=gateway_verified,
            workstation_image_verified=workstation_verified,
            gateway_domain_defined=gateway_defined,
            workstation_domain_defined=workstation_defined,
            network_topology_configured=False,
            lifecycle_stage=lifecycle_stage,
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
            gateway_image_verified=gateway_verified,
            workstation_image_verified=workstation_verified,
            gateway_domain_defined=gateway_defined,
            workstation_domain_defined=workstation_defined,
            network_topology_configured=False,
            lifecycle_stage=lifecycle_stage,
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
        gateway_image_verified=gateway_verified,
        workstation_image_verified=workstation_verified,
        gateway_domain_defined=gateway_defined,
        workstation_domain_defined=workstation_defined,
        network_topology_configured=False,
        lifecycle_stage=lifecycle_stage,
        usable=None,
        confidence="low",
        reason="VM backend is ready and both Gateway/Workstation images are "
        "present at the expected location (stage: " + lifecycle_stage + "), "
        "but Serein never verified their signature/hash, never mapped a "
        "libvirt domain to either specific artifact, never imported them "
        "(no 'virsh define'), and never configured the required internal-"
        "network topology (Section 31-33) - usability stays unknown, "
        "never assumed true from filename presence alone. Verification "
        "requires explicit user-managed action against official Whonix "
        "signature/hash metadata (docs/veil/whonix.md).",
    )
