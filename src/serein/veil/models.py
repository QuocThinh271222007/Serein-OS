"""Structured representations for the Veil privacy-isolation subsystem (S6).

Mirrors the pattern S2-S5 established — dataclasses only, no behavior,
no runtime dependency on any privacy tool. See docs/veil/architecture.md.

The governing principle (docs/veil/threat-model.md): privacy is an
explicit, opt-in workspace boundary, never an invisible global side
effect. Every field here is designed so that "installed"/"present"
booleans never get read as "safe"/"anonymous" — usability and privacy
claims are always separate, conservative fields, and ``None`` always
means genuinely unproven rather than a guessed answer either way.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from serein.cyber.models import VMReadiness
from serein.development.models import ToolStatus

VEIL_CAPABILITIES_SCHEMA_VERSION = 1
VEIL_PLAN_SCHEMA_VERSION = 1

#: The three canonical privacy tiers (Section 4) plus "user-managed" for
#: components Serein documents but never installs/downloads itself
#: (e.g. the official Tor Browser tarball, Whonix VM images).
VEIL_TIERS: tuple[str, ...] = ("host", "workspace", "vm", "user-managed")

#: Machine-readable privacy levels (Section 56) - mechanism names, never
#: a marketing-style confidence label ("low/high anonymity").
PRIVACY_LEVELS: tuple[str, ...] = ("none", "tor_application", "isolated_workspace", "whonix")

#: Component categories for the declarative manifest (``components.py``).
VEIL_CATEGORIES: tuple[str, ...] = (
    "tor-client", "pluggable-transport", "tor-monitor", "browser", "whonix",
)


@dataclass(frozen=True)
class VeilComponentDefinition:
    """One entry in the declarative privacy-tool manifest
    (``components.py``) - data only, never executes anything."""

    id: str
    name: str
    category: str  # one of VEIL_CATEGORIES
    source_type: str  # reuses serein.development's ToolSourceType values
    package: str | None
    recommended_tier: str  # one of VEIL_TIERS
    requires_root: bool  # for INSTALLATION, never runtime
    risk: str  # "none" | "low" | "medium" | "high"
    reason: str


@dataclass
class TorConfigStatus:
    """Read-only ``torrc``/``torrc.d`` directive presence - Section 39-41:
    never reads/stores authentication secrets, cookie content, hashed
    passwords, or bridge line contents; only whether a small, named set
    of directives is present and whether it looks explicitly disabled
    (``0``) or explicitly enabled (any other value). An absent directive
    is ``None`` (unknown), never treated as "unsafe" - Tor's own
    compiled-in defaults matter and are not asserted either way
    (Section 41)."""

    config_present: bool = False
    #: None = no explicit directive found; Tor's own built-in default
    #: (SocksPort 9050 unless disabled) may still apply - never assumed.
    socks_port_configured: bool | None = None
    control_port_configured: bool | None = None
    cookie_authentication_configured: bool | None = None
    #: Presence only (Section 10/41) - TransPort/DNSPort are never
    #: Serein's default mechanism; detecting them is informational.
    trans_port_configured: bool = False
    dns_port_configured: bool = False
    data_directory_configured: bool = False
    #: Presence only - the matched line text itself is never retained
    #: or returned (Section 69/92 - no bridge line leakage).
    bridge_lines_present: bool = False


@dataclass
class TorStatusInfo:
    """Tor is modeled as several genuinely separate questions (Section 6)
    - package/binary presence, service presence/activity, and SOCKS
    evidence are never collapsed into one boolean. ``usable`` is only
    ever ``True`` when there is real, read-only, positive evidence of an
    actual SOCKS surface (an explicit ``SocksPort`` directive or a local
    listening socket) *and* the service is confirmed active - "tor
    binary present" alone, or "service active" alone, never implies
    usability (Section 7)."""

    package_installed: bool = False
    binary: ToolStatus = field(default_factory=lambda: ToolStatus(id="tor"))
    torsocks: ToolStatus = field(default_factory=lambda: ToolStatus(id="torsocks"))
    nyx: ToolStatus = field(default_factory=lambda: ToolStatus(id="nyx"))
    obfs4proxy: ToolStatus = field(default_factory=lambda: ToolStatus(id="obfs4proxy"))
    #: None = systemd/systemctl itself could not be probed (e.g. no
    #: systemd on this host) - never guessed False (Section 42-43).
    service_present: bool | None = None
    service_active: bool | None = None
    #: Which candidate unit name actually matched ("tor.service" or
    #: "tor@default.service") - empty string if none did.
    service_unit: str = ""
    config: TorConfigStatus = field(default_factory=TorConfigStatus)
    #: Read-only local socket evidence only (Section 45) - never an
    #: external connection; None when it could not be determined.
    socks_listener_detected: bool | None = None
    usable: bool | None = None
    confidence: str = "low"  # "high" | "medium" | "low"
    reason: str = "Tor is not installed; nothing to evaluate."


@dataclass
class TorBrowserStatus:
    """Tor Browser is evaluated separately from the system Tor client
    (Section 17/54) - one never implies the other. Serein never scans a
    user's home directory for an unpacked Tor Browser bundle (mirrors
    the "no filesystem-wide search" rule from Section 29, generalized);
    the only detected mechanism is ``torbrowser-launcher``, Ubuntu's
    universe-repo helper that downloads and signature-verifies the
    *official* Tor Project release (see docs/veil/tor-browser.md) - a
    "clean distro integration" (Section 19). Presence of the launcher is
    not proof the actual browser bundle was ever downloaded/run, so
    ``usable`` is always ``None``."""

    launcher: ToolStatus = field(default_factory=lambda: ToolStatus(id="torbrowser-launcher"))
    launcher_installed: bool = False
    usable: bool | None = None
    reason: str = "torbrowser-launcher is not installed; nothing to evaluate."


@dataclass
class OrdinaryBrowserStatus:
    """Informational only - an ordinary browser's presence never implies
    Tor routing or Tor Browser equivalence (Section 105)."""

    firefox: ToolStatus = field(default_factory=lambda: ToolStatus(id="firefox"))
    chromium: ToolStatus = field(default_factory=lambda: ToolStatus(id="chromium"))


@dataclass
class DnsPrivacyStatus:
    """A dedicated DNS-leak state, deliberately never inferred from Tor
    alone (Section 12: "Tor active -> DNS safe" is invalid). Serein's
    recommended route is SOCKS5h (proxy-resolved hostnames) or Tor
    Browser - never host DNS + SOCKS4/plain-SOCKS (Section 11/64)."""

    #: Constant policy, not a probe result: what Serein recommends.
    resolver_strategy: str = "socks5h_or_tor_browser"
    #: Always True - Serein never mutates system DNS (Section 3/102).
    system_dns_unchanged: bool = True
    #: Never proven by S6 - no Apply, no real per-application routing
    #: verification exists yet.
    dns_isolation_proven: bool | None = None
    confidence: str = "low"
    reason: str = ""


@dataclass
class KillSwitchStatus:
    """A kill switch is defined conceptually only (Section 23-24) - S6
    never mutates firewall/network policy, so nothing is ever actually
    configured. ``usable`` is never inferred from firewall package
    presence (Section 58)."""

    available: bool = True  # a future mechanism Serein could plan
    configured: bool = False  # never true - S6 has no Apply engine
    usable: bool | None = None  # never guessed true
    reason: str = (
        "Serein does not mutate firewall/network policy in S6, so no kill "
        "switch is ever actually configured or proven; a workspace that "
        "claims 'Tor-only' must never silently fall back to clearnet if "
        "Tor fails, but Serein cannot currently prove that guarantee."
    )


@dataclass
class VeilWorkspaceReadiness:
    """The single canonical private-workspace readiness verdict (Section
    55) - ``capabilities.py``, ``planner.py``, and ``doctor.py`` all
    consume this instead of each deriving "is a workspace usable"
    independently. ``usable`` is never ``True`` merely because Tor and
    Tor Browser are both installed (Section 57) - S6 never creates or
    configures an actual isolation boundary (no network namespace, no
    container, no browser profile), so ``configured`` is always
    ``False`` and ``usable`` can never legitimately be ``True`` yet."""

    candidate: bool
    configured: bool
    usable: bool | None
    privacy_level: str  # one of PRIVACY_LEVELS
    mechanism: str | None
    reason: str


@dataclass
class WhonixCapabilityInfo:
    """Whonix is modeled as Gateway + Workstation, never a single
    generic VM (Section 25). Reuses S5's ``VMReadiness`` directly
    (Section 27) - no second KVM/QEMU/libvirt detector. Image presence
    is checked only at the exact, documented official Whonix KVM install
    location (``~/.local/share/images/Whonix-{Gateway,Workstation}.qcow2``
    - see docs/veil/whonix.md) - never a filesystem-wide search
    (Section 29), and a matching filename is never trusted as a
    genuine, verified Whonix image (Section 31)."""

    vm_readiness: VMReadiness
    gateway_image_present: bool = False
    workstation_image_present: bool = False
    #: Always False - S6 never configures VM networking (Section 5/32).
    network_topology_configured: bool = False
    usable: bool | None = None
    confidence: str = "low"
    reason: str = ""


@dataclass
class VeilCapability:
    """Mirrors S4/S5's capability shape exactly (Section 46, "reuse
    S4/S5 capability semantics")."""

    id: str
    available: bool | None
    installed: bool
    usable: bool | None
    mechanism: str | None
    source: str | None
    confidence: str  # "high" | "medium" | "low"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VeilCapabilitiesReport:
    schema_version: int
    capabilities: list[VeilCapability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass
class VeilPlanAction:
    """Identical shape to S3/S4/S5's plan action dataclasses."""

    id: str
    component: str
    action: str
    tool: str
    source: str | None
    current: str | None
    target: str | None
    reason: str
    requires_root: bool
    reversible: bool
    risk: str  # "none" | "low" | "medium" | "high"
    verification: str
    status: str  # "APPLY" | "NOOP" | "SKIP" | "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VeilPlan:
    schema_version: int
    actions: list[VeilPlanAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class VeilStatusReport:
    """No ``profile_id``/``profile_status`` fields, unlike S3/S4/S5's
    status reports - deliberately: S6 does not register a global boot
    profile (Section 90/125), so there is no profile state to report
    without fabricating one. See docs/veil/architecture.md."""

    schema_version: int
    tor: TorStatusInfo
    tor_browser: TorBrowserStatus
    ordinary_browser: OrdinaryBrowserStatus
    dns: DnsPrivacyStatus
    kill_switch: KillSwitchStatus
    workspace: VeilWorkspaceReadiness
    whonix: WhonixCapabilityInfo

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
