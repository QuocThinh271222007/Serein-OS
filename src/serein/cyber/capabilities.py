"""``serein cyber capabilities``: which cybersecurity stacks Serein can
safely provision/manage, and whether the underlying tool/mechanism is
actually *usable* — distinct from ``serein cyber status``'s "what
already exists" (mirrors S4's status/capabilities split, Section 22:
"reuse S4 capability semantics").

Every capability's ``usable`` field follows the same three-layer rule
S4 established: tool presence is not the same question as confirmed
usability. ``usable=None`` always means genuinely unverified — never
guessed True. Toolbox/VM-tier capabilities (``web_testing_toolbox``,
``forensics_toolbox``, ``vm_isolation``) report on the underlying
*mechanism* (a container engine, KVM), never claim a toolbox/VM
already exists — S5 has no Apply engine, so nothing has been
provisioned yet.
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.capture import detect_capture_status
from serein.cyber.models import CYBER_CAPABILITIES_SCHEMA_VERSION, CyberCapabilitiesReport
from serein.cyber.models import CyberCapability as Capability
from serein.cyber.network import detect_network_status
from serein.cyber.reverse import detect_reverse_status
from serein.cyber.toolbox import detect_host_hygiene, detect_toolbox_status
from serein.cyber.virtualization import detect_vm_status
from serein.development.containers import container_capability_available
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment


def build_cyber_capabilities(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> CyberCapabilitiesReport:
    environment = detect_environment(root)
    network = detect_network_status(runner=runner)
    capture = detect_capture_status(runner=runner)
    reverse = detect_reverse_status(runner=runner)
    containers = detect_toolbox_status(runner=runner)
    vm = detect_vm_status(runner=runner, root=root)
    hygiene = detect_host_hygiene(runner=runner)

    capabilities: list[Capability] = []

    diag_installed = any(
        t.installed for t in (network.tcpdump, network.mtr, network.ethtool, network.socat)
    )
    capabilities.append(
        Capability(
            "network_diagnostics", True, diag_installed, diag_installed,
            "apt: tcpdump/mtr-tiny/ethtool/socat", "ubuntu-repository", "high",
            "Aggregate host-safe network diagnostic tooling presence.",
        )
    )

    capture_installed = capture.wireshark.installed or capture.tshark.installed
    capabilities.append(
        Capability(
            "packet_capture_tools", True, capture_installed, capture_installed,
            "apt: wireshark/tshark", "ubuntu-repository", "high",
            "Tool presence only - distinct from packet_capture_permission "
            "(see docs/cyber/packet-capture.md).",
        )
    )

    capabilities.append(
        Capability(
            "packet_capture_permission", capture.dumpcap.installed, capture.dumpcap.installed,
            capture.capture_permitted, "dumpcap -D (read-only)", "ubuntu-repository",
            "high" if capture.capture_permitted is not None else "low",
            capture.capture_permission_reason,
        )
    )

    capabilities.append(
        Capability(
            "dns_diagnostics", True, network.dig.installed, network.dig.installed,
            "apt: dnsutils", "ubuntu-repository", "high",
            "dig/nslookup presence - local diagnostic use only.",
        )
    )

    capabilities.append(
        Capability(
            "tls_diagnostics", True, network.openssl.installed, network.openssl.installed,
            "apt: openssl", "ubuntu-repository", "high",
            "openssl s_client/x509 diagnostics - a base OS dependency on Ubuntu.",
        )
    )

    capabilities.append(
        Capability(
            "network_scanning_tools", True, network.nmap.installed, network.nmap.installed,
            "apt: nmap", "ubuntu-repository", "high",
            "Detection only - Serein never invokes nmap against any target "
            "(Section 10/52 of the S5 brief).",
        )
    )

    container_available = container_capability_available(environment)
    toolbox_reason = (
        "Running inside a container: Serein does not plan a nested toolbox here."
        if not container_available
        else "A rootless Podman + Distrobox toolbox is the default mechanism "
        "(S3 architecture, not reopened) - no toolbox has been created by S5."
    )
    capabilities.append(
        Capability(
            "web_testing_toolbox", container_available, False, None,
            "Distrobox + Podman", "ubuntu-repository", "medium", toolbox_reason,
        )
    )

    reverse_installed = any(
        t.installed for t in (reverse.file, reverse.binutils, reverse.gdb, reverse.radare2)
    )
    capabilities.append(
        Capability(
            "reverse_engineering", True, reverse_installed, reverse_installed,
            "apt: file/binutils/gdb; toolbox: radare2/ghidra", "ubuntu-repository", "high",
            "Compact host baseline plus toolbox-tier heavier tools "
            "(Section 13); presence-only, no filesystem-wide binary scan.",
        )
    )

    capabilities.append(
        Capability(
            "forensics_toolbox", container_available, False, None,
            "Distrobox + Podman", "ubuntu-repository", "medium",
            toolbox_reason if not container_available else
            "Heavier forensic tooling (sleuthkit, binwalk) is toolbox-tier by "
            "default (Section 19) - no toolbox has been created by S5.",
        )
    )

    capabilities.append(
        Capability(
            "wireless_tooling", True, hygiene.aircrack_ng.installed, None,
            "apt: aircrack-ng (toolbox-tier)", "ubuntu-repository", "medium",
            "Wireless auditing requires monitor-mode-capable hardware/drivers "
            "and CAP_NET_ADMIN Serein does not verify or grant - usable is "
            "never guessed true (Section 17).",
        )
    )

    container_installed = containers.podman.installed or containers.docker.installed
    toolbox_usable = container_available and container_installed and containers.distrobox.installed
    capabilities.append(
        Capability(
            "container_toolbox", container_available, container_installed, toolbox_usable,
            "podman + distrobox", "ubuntu-repository", "high",
            "Reuses S3's container detection directly - a working engine + "
            "Distrobox means Serein could plan a toolbox; none is created yet.",
        )
    )

    vm_usable = (
        vm.kvm_device_present and vm.kvm_module_loaded
        and vm.user_access is True and vm.qemu.installed
    )
    capabilities.append(
        Capability(
            "vm_isolation", True, vm.qemu.installed or vm.libvirt.installed, vm_usable,
            "qemu-system-x86_64 + KVM", "ubuntu-repository", "high",
            "Full evidence chain required for usable=true: KVM device, "
            "kernel module, user access, and qemu all confirmed (Section 35) "
            "- never inferred from one binary alone. Required for Kali/"
            "malware/full-offensive workloads (Section 20/36).",
        )
    )

    return CyberCapabilitiesReport(
        schema_version=CYBER_CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities
    )
