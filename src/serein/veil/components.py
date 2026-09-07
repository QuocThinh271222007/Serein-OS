"""Serein Veil's declarative privacy-component manifest.

Every component has exactly ONE canonical ``recommended_tier``, mirroring
S5's own manifest discipline. Package names/versions were verified
against the real Ubuntu 26.04 ("resolute") archive via authoritative
package-search evidence gathered for S6 (2026-09) - see
docs/veil/tor-strategy.md and docs/veil/whonix.md. This module is plain
data: nothing here executes apt, a VM operation, or a download.

``recommended_tier="workspace"`` (not "host") for every Tor-related
component: installing the Debian/Ubuntu ``tor`` package starts and
enables a system-wide Tor daemon by default (unlike S5's diagnostic-
only host baseline), so Serein never treats it as a default host
install - it belongs to the explicit, opt-in Veil workspace only
(Section 1/3 - normal host networking stays normal unless the user
explicitly enters a privacy workspace).
"""

from __future__ import annotations

from serein.veil.models import VeilComponentDefinition

VEIL_COMPONENTS: tuple[VeilComponentDefinition, ...] = (
    VeilComponentDefinition(
        "tor", "Tor", "tor-client", "ubuntu-repository", "tor",
        "workspace", True, "low",
        "Anonymizing overlay network daemon (Ubuntu 26.04/resolute: "
        "0.4.9.x, live-verified). Installing the package starts/enables a "
        "system-wide tor.service by default - an explicit, opt-in "
        "workspace-tier action, never part of Serein's default host "
        "baseline (Section 1/3).",
    ),
    VeilComponentDefinition(
        "torsocks", "torsocks", "tor-client", "ubuntu-repository", "torsocks",
        "workspace", True, "low",
        "Explicit per-process SOCKS-wrapping helper (Ubuntu 26.04: "
        "2.5.0-6, live-verified) - an optional convenience, never proof "
        "that an arbitrary wrapped application is leak-free (Section 9); "
        "Serein never invokes it against an external site.",
    ),
    VeilComponentDefinition(
        "nyx", "nyx", "tor-monitor", "ubuntu-repository", "nyx",
        "workspace", True, "none",
        "Terminal Tor status monitor (Ubuntu 26.04: 2.1.0-3build1, "
        "live-verified) - read-only relay/status viewer; Serein never "
        "queries or displays live circuit/relay details itself "
        "(Section 38).",
    ),
    VeilComponentDefinition(
        "obfs4proxy", "obfs4proxy", "pluggable-transport", "ubuntu-repository",
        "obfs4proxy", "workspace", True, "low",
        "Pluggable-transport proxy for censorship-resistant bridges "
        "(Ubuntu 26.04: 0.0.14-2build1, live-verified) - modeled as "
        "optional; Serein never fetches bridge lines or automates bridge "
        "configuration (Section 69).",
    ),
    VeilComponentDefinition(
        "tor-browser", "Tor Browser", "browser", "ubuntu-repository",
        "torbrowser-launcher", "workspace", True, "low",
        "Preferred mechanism for privacy-sensitive web browsing (Section "
        "17) - not equivalent to Firefox + SOCKS (Section 105). "
        "torbrowser-launcher (Ubuntu 26.04 universe: 0.3.9-1build1, "
        "live-verified) downloads and signature-verifies the *official* "
        "torproject.org release; the official tarball itself remains a "
        "valid, equally acceptable user-managed alternative Serein never "
        "downloads on its own behalf (Section 18-19).",
    ),
    VeilComponentDefinition(
        "whonix-gateway", "Whonix-Gateway", "whonix", "user-managed", None,
        "vm", True, "medium",
        "Official Whonix Gateway KVM image (qcow2 + libvirt XML template, "
        "torproject-adjacent Whonix project distribution) - Serein never "
        "downloads, imports, or verifies this image (Section 30-31); only "
        "presence at the documented official install path is detected. "
        "See docs/veil/whonix.md.",
    ),
    VeilComponentDefinition(
        "whonix-workstation", "Whonix-Workstation", "whonix", "user-managed", None,
        "vm", True, "medium",
        "Official Whonix Workstation KVM image - must never be planned "
        "with direct clearnet egress in the canonical topology (Section "
        "32-33/100); routes exclusively through Whonix-Gateway. Serein "
        "never downloads, imports, or verifies this image.",
    ),
)


def all_components() -> list[VeilComponentDefinition]:
    return list(VEIL_COMPONENTS)


def workspace_components() -> list[VeilComponentDefinition]:
    return [c for c in VEIL_COMPONENTS if c.recommended_tier == "workspace"]


def vm_components() -> list[VeilComponentDefinition]:
    return [c for c in VEIL_COMPONENTS if c.recommended_tier == "vm"]
