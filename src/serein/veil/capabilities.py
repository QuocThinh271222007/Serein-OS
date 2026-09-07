"""``serein veil capabilities``: which privacy-isolation mechanisms
Serein can safely describe/plan, and whether each is actually *usable*
- distinct from ``serein veil status``'s "what already exists" (Section
46, "reuse S4/S5 capability semantics").

No capability here may report strong-privacy ``usable=true`` solely
from a component being installed (Section 24/106) - every ``usable``
field traces back to real, read-only evidence computed once in
``tor.py``/``workspace.py``/``whonix.py`` and is never re-derived
independently here.
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.virtualization import detect_vm_status, evaluate_vm_readiness
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment
from serein.veil.browser import detect_tor_browser_status
from serein.veil.dns import evaluate_dns_privacy
from serein.veil.models import VEIL_CAPABILITIES_SCHEMA_VERSION, VeilCapabilitiesReport
from serein.veil.models import VeilCapability as Capability
from serein.veil.tor import detect_tor_status
from serein.veil.whonix import detect_whonix_status
from serein.veil.workspace import evaluate_kill_switch, evaluate_workspace_readiness


def build_veil_capabilities(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> VeilCapabilitiesReport:
    environment = detect_environment(root)
    tor = detect_tor_status(runner=runner, root=root)
    tor_browser = detect_tor_browser_status(runner=runner)
    dns = evaluate_dns_privacy(tor)
    kill_switch = evaluate_kill_switch()
    workspace = evaluate_workspace_readiness(tor, tor_browser, environment.is_container)
    whonix = detect_whonix_status(runner=runner, root=root, home=home)
    vm = detect_vm_status(runner=runner, root=root)
    vm_readiness = evaluate_vm_readiness(vm)

    capabilities: list[Capability] = []

    capabilities.append(
        Capability(
            "tor_client", True, tor.package_installed, tor.usable, "apt: tor",
            "ubuntu-repository", tor.confidence, tor.reason,
        )
    )

    capabilities.append(
        Capability(
            "tor_socks", True, tor.torsocks.installed, None, "apt: torsocks",
            "ubuntu-repository", "low",
            "torsocks is an optional per-process SOCKS-wrapping helper - its "
            "presence is never treated as proof that an arbitrary wrapped "
            "application is leak-free (Section 9); Serein never invokes it "
            "against any external site.",
        )
    )

    capabilities.append(
        Capability(
            "tor_browser", True, tor_browser.launcher_installed, tor_browser.usable,
            "torbrowser-launcher (official Tor Project release)",
            "ubuntu-repository", "medium" if tor_browser.launcher_installed else "low",
            tor_browser.reason,
        )
    )

    capabilities.append(
        Capability(
            "private_browser_profile", True, False, None,
            "separate profile directory + SOCKS5h (planned only)", "user-managed", "low",
            "S6 only plans/detects a future isolated browser profile - it "
            "never creates one, never touches an existing profile, and "
            "never shares history/extensions/cookies by default when it "
            "eventually does (Section 16).",
        )
    )

    capabilities.append(
        Capability(
            "dns_isolation", True, False, dns.dns_isolation_proven,
            "SOCKS5h / Tor Browser (recommended)", None, dns.confidence, dns.reason,
        )
    )

    capabilities.append(
        Capability(
            "tor_only_routing", True, False, None, None, None, "low",
            "No capability may report a 'Tor-only'/anonymous routing claim "
            "as usable=true without the entire evidence chain proven "
            "(Section 24/106) - S6 has no mechanism to configure or verify "
            "Tor-only routing yet, so this is always unproven.",
        )
    )

    capabilities.append(
        Capability(
            "kill_switch", kill_switch.available, kill_switch.configured,
            kill_switch.usable, "future firewall/network-policy enforcement "
            "(not implemented)", None, "low", kill_switch.reason,
        )
    )

    capabilities.append(
        Capability(
            "private_workspace", workspace.candidate, workspace.configured,
            workspace.usable, workspace.mechanism, "user-managed", "low",
            f"privacy_level={workspace.privacy_level}. {workspace.reason}",
        )
    )

    capabilities.append(
        Capability(
            "whonix_vm", True, whonix.gateway_image_present and whonix.workstation_image_present,
            whonix.usable, "Whonix-Gateway + Whonix-Workstation qcow2 images",
            "user-managed", whonix.confidence, whonix.reason,
        )
    )

    capabilities.append(
        Capability(
            "vm_privacy_boundary", True, vm.qemu.installed or vm.libvirt.installed,
            vm_readiness.usable, "qemu-system-x86 + libvirt + KVM", "ubuntu-repository",
            "high", vm_readiness.reason + " Required for Whonix Gateway/"
            "Workstation isolation (Section 25/34) - reused directly from "
            "S5's VM readiness (Section 27), not re-derived.",
        )
    )

    return VeilCapabilitiesReport(
        schema_version=VEIL_CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities
    )
