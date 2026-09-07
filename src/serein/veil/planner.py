"""``serein veil plan [component]``: deterministic, evidence-based
Veil privacy planning.

No Apply mechanism exists (Section 5) - this module only ever reads
state and proposes ``VeilPlanAction``s with an explicit ``status`` of
``APPLY``/``NOOP``/``SKIP``/``BLOCKED``. Nothing here writes a package,
starts a service, mutates ``torrc``, creates a network namespace,
creates/imports a VM, or downloads anything (Whonix image or Tor
Browser bundle alike). A plan is a pure function of on-disk/PATH state.

Components are ``tor``/``workspace``/``whonix`` (Section 5's own
focused-plan list), distinct from S5 cyber's ``host``/``toolbox``/``vm``
vocabulary - Veil's tiering has different semantics (Section 86) and
reusing cyber's component names would misleadingly imply a "host"
install baseline that does not exist here.

Some actions here are always ``APPLY``/``BLOCKED`` placeholders for a
future Apply engine that does not exist yet (Section 51: "Most VM/
workspace actions may be BLOCKED/SKIP/NOOP/APPLY as future planned
actions. No execution.") - the status label communicates what a future
Serein *would* propose next, never something this phase performs.
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.models import VMReadiness
from serein.development.dpkg import apt_package_installed
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.veil.browser import detect_tor_browser_status
from serein.veil.models import VEIL_PLAN_SCHEMA_VERSION, TorStatusInfo, VeilPlan, VeilPlanAction
from serein.veil.tor import detect_tor_status
from serein.veil.whonix import detect_whonix_status
from serein.veil.workspace import evaluate_kill_switch

VALID_COMPONENTS: tuple[str, ...] = ("tor", "workspace", "whonix")

_VM_PACKAGES = "qemu-system-x86, libvirt-daemon-system, libvirt-clients"

_VM_BLOCKED_STATUSES = (
    "blocked_no_hardware", "blocked_module_missing",
    "blocked_no_access", "blocked_access_unknown",
)


def _tor_package_action(tor: TorStatusInfo, runner: CommandRunner) -> VeilPlanAction:
    action_id, component, action = "tor.package", "tor", "install_apt_packages"
    if apt_package_installed("tor", runner=runner) or tor.package_installed:
        return VeilPlanAction(
            action_id, component, action, "tor", "ubuntu-repository",
            "installed", "installed",
            "The tor package is already installed. Installing it does not "
            "by itself route any traffic - normal host networking remains "
            "unaffected (Section 1/3) until a workspace explicitly uses it.",
            False, True, "none", "tor --version", "NOOP",
        )
    return VeilPlanAction(
        action_id, component, action, "tor", "ubuntu-repository",
        "not installed", "tor",
        "The tor package is not installed. Installing it starts/enables a "
        "system-wide tor.service by default - a deliberate workspace-tier "
        "action, never part of any default host baseline.",
        True, True, "low", "tor --version", "APPLY",
    )


def _torsocks_action(tor: TorStatusInfo, runner: CommandRunner) -> VeilPlanAction:
    action_id, component, action = "tor.torsocks", "tor", "install_apt_packages"
    if tor.torsocks.installed:
        return VeilPlanAction(
            action_id, component, action, "torsocks", "ubuntu-repository",
            tor.torsocks.version, tor.torsocks.version,
            "torsocks is already installed.", False, True, "none",
            "torsocks --version", "NOOP",
        )
    return VeilPlanAction(
        action_id, component, action, "torsocks", "ubuntu-repository",
        "not installed", "torsocks",
        "torsocks is an optional per-process SOCKS-wrapping helper "
        "(Section 9) - never required, never proof of leak-free behavior "
        "for an arbitrary wrapped application.",
        True, True, "low", "torsocks --version", "APPLY",
    )


def _tor_browser_action(runner: CommandRunner) -> VeilPlanAction:
    action_id, component, action = "browser.tor_browser", "workspace", "install_apt_packages"
    status = detect_tor_browser_status(runner=runner)
    if status.launcher_installed:
        return VeilPlanAction(
            action_id, component, action, "torbrowser-launcher", "ubuntu-repository",
            "installed", "installed",
            "torbrowser-launcher is already installed. It downloads/"
            "verifies the official Tor Browser release on first user-"
            "initiated run - Serein never triggers that itself.",
            False, True, "none", "torbrowser-launcher --version", "NOOP",
        )
    return VeilPlanAction(
        action_id, component, action, "torbrowser-launcher", "ubuntu-repository",
        "not installed", "torbrowser-launcher",
        "torbrowser-launcher is not installed. Installing the launcher is "
        "a normal apt package install - it does not itself download the "
        "Tor Browser bundle (Section 18-19); Tor Browser remains preferred "
        "over Firefox + SOCKS for privacy-sensitive browsing (Section 17).",
        True, True, "low", "torbrowser-launcher --version", "APPLY",
    )


def _workspace_private_profile_action(tor: TorStatusInfo) -> VeilPlanAction:
    action_id, component = "workspace.private_profile", "workspace"
    action = "create_isolated_profile"
    if tor.usable is not True:
        return VeilPlanAction(
            action_id, component, action, "isolated browser profile", None,
            "blocked", None,
            "Tor client usability is not confirmed, so an isolated privacy "
            "profile would have nothing safe to route through yet.",
            False, True, "none", "n/a", "BLOCKED",
        )
    return VeilPlanAction(
        action_id, component, action, "isolated browser profile", "user-managed",
        "not created", "separate profile directory (future)",
        "Tor is usable; a future Apply engine could create a separate "
        "profile directory with its own cookie/storage state, no shared "
        "history, and no shared extensions by default (Section 16). Not "
        "created now - S6 has no Apply engine and never touches an "
        "existing browser profile.",
        False, True, "low", "n/a", "APPLY",
    )


def _workspace_routing_action() -> VeilPlanAction:
    """Informational, always NOOP - documents the SOCKS5h-over-
    transparent-proxying policy as a concrete, testable plan action
    (Section 10-11), mirroring S5's ``vm.isolation_policy`` pattern."""
    return VeilPlanAction(
        "workspace.routing", "workspace", "report_only",
        "SOCKS5h (application-level)", None, None, None,
        "Transparent Tor proxying (TransPort/DNSPort/iptables-nft "
        "redirect) is NOT the S6 default - the preferred application "
        "boundary is SOCKS5h (proxy-resolved hostnames), or Tor Browser "
        "for web browsing. Serein never mutates system DNS, the default "
        "route, or firewall rules to build a transparent boundary "
        "(Section 3/10-11).",
        False, True, "none", "n/a", "NOOP",
    )


def _workspace_kill_switch_action() -> VeilPlanAction:
    kill_switch = evaluate_kill_switch()
    return VeilPlanAction(
        "workspace.kill_switch_policy", "workspace", "report_only",
        "kill switch (conceptual)", None, "not configured", None,
        kill_switch.reason, False, True, "none", "n/a", "NOOP",
    )


def _whonix_vm_prerequisites_action(readiness: VMReadiness) -> VeilPlanAction:
    action_id, component, action = "whonix.vm_prerequisites", "whonix", "install_apt_packages"
    if readiness.status in _VM_BLOCKED_STATUSES:
        return VeilPlanAction(
            action_id, component, action, _VM_PACKAGES, "ubuntu-repository",
            readiness.status, None, readiness.reason, False, True, "none", "n/a", "BLOCKED",
        )
    if readiness.status == "ready":
        return VeilPlanAction(
            action_id, component, action, _VM_PACKAGES, "ubuntu-repository",
            "installed", "installed", readiness.reason, False, True, "none",
            "qemu-system-x86_64 --version", "NOOP",
        )
    return VeilPlanAction(
        action_id, component, action, _VM_PACKAGES, "ubuntu-repository",
        "not installed", _VM_PACKAGES,
        readiness.reason + " Reused directly from S5's VM readiness "
        "(Section 27) - Serein never creates a VM, never downloads an "
        "image, and never modifies groups.",
        True, True, "low", "qemu-system-x86_64 --version", "APPLY",
    )


def _whonix_artifact_action(
    image_id: str, present: bool, readiness_status: str, readiness_reason: str
) -> VeilPlanAction:
    """Artifact *presence* only (S6R Corrective D, Section 35) - a
    separate, distinctly-named action from verification below, so an
    ``APPLY``/``NOOP`` here never reads as "Whonix is ready"."""
    action_id, component, action = f"whonix.{image_id}_artifact", "whonix", "detect_vm_image"
    tool = f"Whonix-{image_id.capitalize()}.qcow2"
    if readiness_status in _VM_BLOCKED_STATUSES or readiness_status != "ready":
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "blocked", None,
            "VM backend is not ready yet (" + readiness_status + "): "
            + readiness_reason, False, True, "none", "n/a", "BLOCKED",
        )
    if present:
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "present", "present",
            f"{tool} is present at the expected location. Presence alone "
            f"is never verification - see whonix.{image_id}_verification.",
            False, True, "none", "n/a", "NOOP",
        )
    return VeilPlanAction(
        action_id, component, action, tool, "user-managed",
        "not present", tool,
        f"{tool} is not present. Serein never downloads a Whonix image "
        "(Section 30) - future provisioning would require the official "
        "source documented in docs/veil/whonix.md.",
        True, True, "medium", "n/a", "APPLY",
    )


def _whonix_verification_action(
    image_id: str, present: bool, verified: bool | None
) -> VeilPlanAction:
    """Signature/hash verification is a distinct, later step Serein
    never performs itself (S6R Corrective D, Section 32/36) - this
    action is BLOCKED, not APPLY/NOOP, whenever the artifact is absent
    or unverified, so a plan reader is never told verification is
    "done" or "actionable by Serein" when it is neither."""
    action_id, component, action = f"whonix.{image_id}_verification", "whonix", "verify_vm_image"
    tool = f"Whonix-{image_id.capitalize()}.qcow2 signature/hash verification"
    if not present:
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "blocked", None,
            f"{image_id.capitalize()} image is not present yet - nothing "
            "to verify.",
            False, True, "none", "n/a", "BLOCKED",
        )
    if verified:
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "verified", "verified", "Verification already confirmed.",
            False, True, "none", "n/a", "NOOP",
        )
    return VeilPlanAction(
        action_id, component, action, tool, "user-managed",
        "unverified", None,
        "Serein never performs OpenPGP/signify/hash verification "
        "automatically (Section 31-32) - this requires explicit user-"
        "managed verification against official Whonix signature/hash "
        "metadata (docs/veil/whonix.md) before the image can be trusted. "
        "A matching filename is never treated as verified (Section 37).",
        False, True, "none", "n/a", "BLOCKED",
    )


def _whonix_network_topology_action(
    gateway_present: bool, workstation_present: bool,
    gateway_verified: bool | None, workstation_verified: bool | None,
    gateway_defined: bool | None, workstation_defined: bool | None,
    readiness_status: str, readiness_reason: str,
) -> VeilPlanAction:
    """Topology may only ever reach ``APPLY`` once both artifacts are
    present, verified, AND imported/defined (S6R Corrective D, Section
    34) - never merely "present". Since Serein performs no verification
    or import itself, this remains ``BLOCKED`` in every real build
    today - an explicitly accepted, documented outcome (Section 34:
    "In S6's current no-Apply phase, likely topology remains BLOCKED in
    all real cases. That is acceptable.")."""
    action_id, component, action = "whonix.network_topology", "whonix", "configure_vm_network"
    tool = "internal-only Whonix-Workstation adapter (never direct clearnet egress)"
    if readiness_status != "ready":
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "blocked", None,
            "VM backend is not ready yet: " + readiness_reason,
            False, True, "none", "n/a", "BLOCKED",
        )
    if not (gateway_present and workstation_present):
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "blocked", None,
            "Both Whonix images must be present before topology can be "
            "considered.",
            False, True, "none", "n/a", "BLOCKED",
        )
    if not (gateway_verified and workstation_verified):
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "blocked", None,
            "Both Whonix images are present but not verified - Serein "
            "never trusts a matching filename alone (Section 31/37); "
            "topology configuration cannot proceed on an unverified "
            "artifact.",
            False, True, "none", "n/a", "BLOCKED",
        )
    if not (gateway_defined and workstation_defined):
        return VeilPlanAction(
            action_id, component, action, tool, "user-managed",
            "blocked", None,
            "Both Whonix images are verified but not yet imported as "
            "libvirt domains ('virsh define') - topology configuration "
            "requires both domains to exist first.",
            False, True, "none", "n/a", "BLOCKED",
        )
    return VeilPlanAction(
        action_id, component, action, tool, "user-managed",
        "not configured", tool,
        "Both Whonix domains are verified and imported. Future topology "
        "configuration MUST route Whonix-Workstation exclusively through "
        "Whonix-Gateway -> NAT/host uplink: Whonix-Workstation must never "
        "be planned with a direct clearnet-facing network adapter "
        "(Section 32-33/100) - this invariant is enforced regardless of "
        "any future Apply engine implementation.",
        True, True, "medium", "n/a", "APPLY",
    )


def build_veil_plan(
    component: str | None = None,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
    home: Path | None = None,
) -> VeilPlan:
    if component is not None and component not in VALID_COMPONENTS:
        raise ValueError(f"unknown veil plan component: {component!r}")

    tor = detect_tor_status(runner=runner, root=root)
    whonix = detect_whonix_status(runner=runner, root=root, home=home)
    readiness = whonix.vm_readiness

    actions = [
        _tor_package_action(tor, runner),
        _torsocks_action(tor, runner),
        _tor_browser_action(runner),
        _workspace_private_profile_action(tor),
        _workspace_routing_action(),
        _workspace_kill_switch_action(),
        _whonix_vm_prerequisites_action(readiness),
        _whonix_artifact_action(
            "gateway", whonix.gateway_image_present, readiness.status, readiness.reason
        ),
        _whonix_verification_action(
            "gateway", whonix.gateway_image_present, whonix.gateway_image_verified
        ),
        _whonix_artifact_action(
            "workstation", whonix.workstation_image_present, readiness.status, readiness.reason
        ),
        _whonix_verification_action(
            "workstation", whonix.workstation_image_present, whonix.workstation_image_verified
        ),
        _whonix_network_topology_action(
            whonix.gateway_image_present, whonix.workstation_image_present,
            whonix.gateway_image_verified, whonix.workstation_image_verified,
            whonix.gateway_domain_defined, whonix.workstation_domain_defined,
            readiness.status, readiness.reason,
        ),
    ]

    if component is not None:
        actions = [a for a in actions if a.component == component]

    return VeilPlan(schema_version=VEIL_PLAN_SCHEMA_VERSION, actions=actions)
