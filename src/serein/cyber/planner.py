"""``serein cyber plan [component]``: deterministic, evidence-based
cybersecurity workspace planning.

No Apply mechanism exists in S5 (Section 4) - this module only ever
reads state and proposes ``CyberPlanAction``s with an explicit
``status`` of ``APPLY``/``NOOP``/``SKIP``/``BLOCKED``. Nothing here
writes a package, creates a container, creates a VM, downloads an ISO,
captures a packet, or scans a network. A plan is a pure function of
on-disk/PATH state.

Components are intentionally just ``host``/``toolbox``/``vm``
(Section 56, the CLI's own final, authoritative list — an earlier
draft section suggested finer network/reverse sub-filters, but
splitting host actions by category would require either duplicating a
tool's install action across two components or introducing ambiguous
overlap; Section 25 explicitly permits skipping that granularity "only
if architecture remains clean," and this does).
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.capture import detect_capture_status
from serein.cyber.models import (
    CYBER_PLAN_SCHEMA_VERSION,
    CyberContainerStatusInfo,
    CyberPlan,
    CyberPlanAction,
    NetworkDiagnosticsStatus,
    PacketCaptureStatus,
    ReverseEngineeringStatus,
    VMCapabilityInfo,
)
from serein.cyber.network import detect_network_status
from serein.cyber.reverse import detect_reverse_status
from serein.cyber.toolbox import detect_toolbox_status
from serein.cyber.tools import default_host_tools
from serein.cyber.virtualization import detect_vm_status, evaluate_vm_readiness
from serein.development.models import ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment

VALID_COMPONENTS: tuple[str, ...] = ("host", "toolbox", "vm")


def _host_installed_map(
    network: NetworkDiagnosticsStatus,
    capture: PacketCaptureStatus,
    reverse: ReverseEngineeringStatus,
    exiftool: ToolStatus,
) -> dict[str, bool]:
    return {
        "nmap": network.nmap.installed,
        "tcpdump": network.tcpdump.installed,
        "bind9-dnsutils": network.dig.installed,
        "whois": network.whois.installed,
        "openssl": network.openssl.installed,
        "socat": network.socat.installed,
        "netcat-openbsd": network.netcat.installed,
        "mtr-tiny": network.mtr.installed,
        "ethtool": network.ethtool.installed,
        "tshark": capture.tshark.installed,
        "file": reverse.file.installed,
        "binutils": reverse.binutils.installed,
        "libimage-exiftool-perl": exiftool.installed,
    }


def _host_baseline_action(
    network: NetworkDiagnosticsStatus,
    capture: PacketCaptureStatus,
    reverse: ReverseEngineeringStatus,
    exiftool: ToolStatus,
) -> CyberPlanAction:
    """One canonical Host Cyber Light group action (Section 27 —
    "create ONE canonical manifest, do not create a kitchen sink"),
    mirroring S3's ``_base_action``/``_apt_group_action`` pattern.

    Uses ``default_host_tools()`` (default-install subset), never every
    ``recommended_tier == "host"`` tool — a tool can be host-appropriate
    without being part of the forced default baseline (Wireshark's GUI
    package is the concrete example; S5R corrective Section 14)."""
    host_tools = [t for t in default_host_tools() if t.package]
    installed_map = _host_installed_map(network, capture, reverse, exiftool)
    missing = [t for t in host_tools if not installed_map.get(t.package or "", False)]
    tool_names = ", ".join(t.package or t.id for t in host_tools)
    verify = "dpkg -s <package> 2>&1 | grep Status"
    if not missing:
        return CyberPlanAction(
            "host.baseline", "host", "install_apt_packages", tool_names,
            "ubuntu-repository", "installed", "installed",
            "All Host Cyber Light packages are already installed.",
            False, True, "none", verify, "NOOP",
        )
    missing_names = ", ".join(t.package or t.id for t in missing)
    return CyberPlanAction(
        "host.baseline", "host", "install_apt_packages", tool_names, "ubuntu-repository",
        "partially installed" if len(missing) < len(host_tools) else "not installed",
        tool_names,
        f"Missing package(s): {missing_names}. Compact, high-value diagnostic/"
        "capture/reverse-engineering baseline - never a full Kali-style "
        "toolset (Section 78 invariant).",
        True, True, "low", verify, "APPLY",
    )


def _toolbox_engine_action(
    containers: CyberContainerStatusInfo, environment_is_container: bool
) -> CyberPlanAction:
    action_id, component, action = "toolbox.engine", "toolbox", "install_apt_packages"
    if environment_is_container:
        return CyberPlanAction(
            action_id, component, action, "podman", "ubuntu-repository", "not applicable",
            None, "Running inside a container: Serein does not plan a nested "
            "toolbox engine here.", False, True, "none", "n/a", "SKIP",
        )
    if containers.podman.installed or containers.docker.installed:
        engines = [n for n, s in (("podman", containers.podman), ("docker", containers.docker))
                   if s.installed]
        return CyberPlanAction(
            action_id, component, action, "podman", "ubuntu-repository",
            ", ".join(engines), ", ".join(engines),
            f"Container engine(s) already present ({', '.join(engines)}); "
            "Serein will not install a competing engine (S3 ADR-0011, not "
            "reopened here).", False, True, "none",
            "podman --version || docker --version", "NOOP",
        )
    return CyberPlanAction(
        action_id, component, action, "podman", "ubuntu-repository", "not installed", "podman",
        "Rootless Podman is the default toolbox engine (Section 5/29-31) - "
        "never --privileged, never --network=host by default.",
        True, True, "low", "podman --version", "APPLY",
    )


def _toolbox_distrobox_action(
    containers: CyberContainerStatusInfo, environment_is_container: bool
) -> CyberPlanAction:
    action_id, component, action = "toolbox.distrobox", "toolbox", "install_apt_packages"
    if environment_is_container:
        return CyberPlanAction(
            action_id, component, action, "distrobox", "ubuntu-repository", "not applicable",
            None, "Running inside a container: Distrobox needs a container "
            "engine backend, unavailable here.", False, True, "none", "n/a", "SKIP",
        )
    if containers.distrobox.installed:
        return CyberPlanAction(
            action_id, component, action, "distrobox", "ubuntu-repository",
            containers.distrobox.version, containers.distrobox.version,
            "Distrobox is already installed.", False, True, "none",
            "distrobox --version", "NOOP",
        )
    return CyberPlanAction(
        action_id, component, action, "distrobox", "ubuntu-repository", "not installed",
        "distrobox",
        "General cyber toolbox target is Ubuntu/Debian-based via Distrobox "
        "(Section 29) - not a Kali container by default (Section 30); a "
        "Kali toolbox may be documented as an optional, non-default choice "
        "later, never the universal default.",
        True, True, "low", "distrobox --version", "APPLY",
    )


_VM_PACKAGES = "qemu-system-x86, libvirt-daemon-system, libvirt-clients"


_VM_BLOCKED_STATUSES = (
    "blocked_no_hardware", "blocked_module_missing",
    "blocked_no_access", "blocked_access_unknown",
)


def _vm_prerequisites_action(vm: VMCapabilityInfo) -> CyberPlanAction:
    """``tool``/``target`` list real Ubuntu apt package names, not the
    probed binary names (``qemu-system-x86_64``/``virsh``) - live
    validation on Ubuntu 26.04 found no ``qemu-system-x86_64`` or
    ``libvirt`` package (see docs/validation/s5/package-validation.md);
    the packages that actually provide those binaries are
    ``qemu-system-x86`` and ``libvirt-daemon-system``/``libvirt-clients``.

    Consumes ``evaluate_vm_readiness()`` (S5R Section 17-18) - the same
    canonical verdict ``capabilities.py``'s ``vm_isolation`` and
    ``doctor.py``'s VM check use, so ``vm_isolation.usable == True``
    always implies this action's status is ``NOOP`` (Section 22/43
    invariant) and a present-but-inaccessible/unknown-access ``/dev/kvm``
    is always ``BLOCKED``, never treated as though prerequisites alone
    make a VM usable (Section 19-20)."""
    action_id, component, action = "vm.prerequisites", "vm", "install_apt_packages"
    readiness = evaluate_vm_readiness(vm)
    if readiness.status in _VM_BLOCKED_STATUSES:
        return CyberPlanAction(
            action_id, component, action, _VM_PACKAGES, "ubuntu-repository",
            readiness.status, None, readiness.reason,
            False, True, "none", "n/a", "BLOCKED",
        )
    if readiness.status == "ready":
        return CyberPlanAction(
            action_id, component, action, _VM_PACKAGES, "ubuntu-repository",
            "installed", "installed", readiness.reason,
            False, True, "none", "qemu-system-x86_64 --version", "NOOP",
        )
    # needs_qemu / needs_libvirt: hardware+access already confirmed ready,
    # only the package layer is missing.
    return CyberPlanAction(
        action_id, component, action, _VM_PACKAGES, "ubuntu-repository",
        "not installed", _VM_PACKAGES,
        readiness.reason + " Serein never creates a VM, never downloads an "
        "ISO, and never modifies groups (Section 34/66/67).",
        True, True, "low", "qemu-system-x86_64 --version", "APPLY",
    )


def _vm_isolation_policy_action() -> CyberPlanAction:
    """Informational, always NOOP - documents the Kali/malware VM
    boundary as a concrete, testable plan action (mirrors S4's
    ``voice.workload_note`` report_only pattern), Section 36/20."""
    return CyberPlanAction(
        "vm.isolation_policy", "vm", "report_only",
        "Kali / untrusted binaries / kernel-sensitive labs", None, None, None,
        "Full Kali environments, untrusted/malicious binaries, kernel "
        "exploit labs, and network-isolation experiments require a VM "
        "boundary - the isolated Distrobox/Podman toolbox is not sufficient "
        "isolation for hostile kernel/userspace samples and Serein never "
        "claims otherwise. See docs/cyber/vm-isolation.md.",
        False, True, "none", "n/a", "NOOP",
    )


def build_cyber_plan(
    component: str | None = None,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
) -> CyberPlan:
    if component is not None and component not in VALID_COMPONENTS:
        raise ValueError(f"unknown cyber plan component: {component!r}")

    network = detect_network_status(runner=runner)
    capture = detect_capture_status(runner=runner)
    reverse = detect_reverse_status(runner=runner)
    exiftool = probe_tool("exiftool", "exiftool", runner=runner)
    containers = detect_toolbox_status(runner=runner)
    vm = detect_vm_status(runner=runner, root=root)
    environment_is_container = detect_environment(root).is_container

    actions = [
        _host_baseline_action(network, capture, reverse, exiftool),
        _toolbox_engine_action(containers, environment_is_container),
        _toolbox_distrobox_action(containers, environment_is_container),
        _vm_prerequisites_action(vm),
        _vm_isolation_policy_action(),
    ]

    if component is not None:
        actions = [a for a in actions if a.component == component]

    return CyberPlan(schema_version=CYBER_PLAN_SCHEMA_VERSION, actions=actions)
