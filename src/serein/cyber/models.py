"""Structured representations for the cybersecurity workspace subsystem.

Mirrors the pattern S2/S3/S4 established — dataclasses only, no
behavior, no runtime dependency on any security tool. See
``docs/cyber/architecture.md``.

S5 reuses ``serein.development.models.ToolStatus`` and
``serein.development.runner.CommandRunner`` directly (Section 59 —
no second detection/subprocess framework) but defines its own
``CyberToolDefinition``/``CyberCapability``/``CyberPlanAction`` shapes,
richer than S3's ``ToolDefinition`` (category, tier, network-privilege,
risk) — the same reasoning S4 used for ``AIPlanAction`` rather than
reusing S3's ``DevPlanAction`` directly: structurally similar, but a
distinct, independently versioned machine-readable surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from serein.development.models import ToolStatus

CYBER_CAPABILITIES_SCHEMA_VERSION = 1
CYBER_PLAN_SCHEMA_VERSION = 1

#: Independent of ``serein.__version__``; bumped only if S5 ever ships
#: a managed config resource (none does yet).
CYBER_CONFIG_VERSION = 1

#: The three operational tiers (Section 5) plus "user-managed" for
#: proprietary/GUI tools Serein documents but never installs (e.g.
#: Burp Suite). Every tool has exactly one canonical
#: ``recommended_tier`` — the planner filters by tier, it never
#: maintains a second, potentially-drifting classification (Section 62).
CYBER_TIERS: tuple[str, ...] = ("host", "toolbox", "vm", "user-managed")

#: Tool categories (Section 21) — informational grouping, not a second
#: tiering system.
CYBER_CATEGORIES: tuple[str, ...] = (
    "network-diagnostics", "packet-capture", "reverse-engineering",
    "forensics", "web-security", "wireless", "password-audit",
    "exploit-framework", "malware-analysis",
)


@dataclass(frozen=True)
class CyberToolDefinition:
    """One entry in the declarative tool manifest (``tools.py``) —
    data only, never executes anything. See docs/cyber/tool-classification.md."""

    id: str
    name: str
    category: str  # one of CYBER_CATEGORIES
    source_type: str  # reuses serein.development's ToolSourceType values
    package: str | None
    recommended_tier: str  # one of CYBER_TIERS
    requires_root: bool  # for INSTALLATION, never runtime (Section 82)
    requires_network_privilege: bool  # e.g. raw sockets/CAP_NET_RAW at runtime
    reversible: bool
    risk: str  # "none" | "low" | "medium" | "high"
    reason: str


@dataclass
class NetworkDiagnosticsStatus:
    """Host-safe network/DNS/TLS diagnostic tools only (Section 6/11) —
    never a scanning/offensive tool's runtime state."""

    nmap: ToolStatus = field(default_factory=lambda: ToolStatus(id="nmap"))
    tcpdump: ToolStatus = field(default_factory=lambda: ToolStatus(id="tcpdump"))
    dig: ToolStatus = field(default_factory=lambda: ToolStatus(id="dig"))
    whois: ToolStatus = field(default_factory=lambda: ToolStatus(id="whois"))
    socat: ToolStatus = field(default_factory=lambda: ToolStatus(id="socat"))
    netcat: ToolStatus = field(default_factory=lambda: ToolStatus(id="netcat"))
    mtr: ToolStatus = field(default_factory=lambda: ToolStatus(id="mtr"))
    ethtool: ToolStatus = field(default_factory=lambda: ToolStatus(id="ethtool"))
    openssl: ToolStatus = field(default_factory=lambda: ToolStatus(id="openssl"))


@dataclass
class PacketCaptureStatus:
    """Capture *tool presence* and capture *privilege* are modeled as
    two separate questions (Section 8/9) — privilege is only ever
    derived from real, read-only evidence (``dumpcap -D``, which lists
    capture-capable interfaces without capturing a single packet - the
    officially documented safe permission check), never inferred from
    tool presence alone."""

    wireshark: ToolStatus = field(default_factory=lambda: ToolStatus(id="wireshark"))
    tshark: ToolStatus = field(default_factory=lambda: ToolStatus(id="tshark"))
    dumpcap: ToolStatus = field(default_factory=lambda: ToolStatus(id="dumpcap"))
    #: True/False only from real `dumpcap -D` evidence; None when
    #: dumpcap isn't installed or the check couldn't run.
    capture_permitted: bool | None = None
    capture_permission_reason: str = "dumpcap not installed; nothing to evaluate."


@dataclass
class ReverseEngineeringStatus:
    """Compact host-safe baseline (Section 13) — gdb/strace are reused
    directly from S3's ``serein.development.cpp`` detection rather than
    re-probed (Section 59), since S3 already owns that exact evidence."""

    file: ToolStatus = field(default_factory=lambda: ToolStatus(id="file"))
    binutils: ToolStatus = field(default_factory=lambda: ToolStatus(id="binutils"))
    gdb: ToolStatus = field(default_factory=lambda: ToolStatus(id="gdb"))
    strace: ToolStatus = field(default_factory=lambda: ToolStatus(id="strace"))
    radare2: ToolStatus = field(default_factory=lambda: ToolStatus(id="radare2"))
    #: Ghidra has no reliable single PATH binary in every install
    #: method (self-contained release archive, no Ubuntu package as of
    #: the live validation this pass performed) - best-effort probe
    #: only, documented as user-managed. See docs/cyber/reverse-engineering.md.
    ghidra: ToolStatus = field(default_factory=lambda: ToolStatus(id="ghidra"))


@dataclass
class CyberContainerStatusInfo:
    """Reuses S3's container detection directly (Section 59 — never
    re-probed independently)."""

    podman: ToolStatus = field(default_factory=lambda: ToolStatus(id="podman"))
    docker: ToolStatus = field(default_factory=lambda: ToolStatus(id="docker"))
    distrobox: ToolStatus = field(default_factory=lambda: ToolStatus(id="distrobox"))


@dataclass
class HostHygieneStatus:
    """Doctor-support evidence only (Section 24): a small set of
    tools that should never ordinarily be found on the host baseline
    (they belong in the isolated toolbox or a VM). Presence here is
    not itself wrong - a user may have installed them deliberately -
    but the doctor surfaces it as a WARN-level observation, never a
    FAIL, and Serein never removes anything."""

    hashcat: ToolStatus = field(default_factory=lambda: ToolStatus(id="hashcat"))
    john: ToolStatus = field(default_factory=lambda: ToolStatus(id="john"))
    metasploit: ToolStatus = field(default_factory=lambda: ToolStatus(id="msfconsole"))
    sqlmap: ToolStatus = field(default_factory=lambda: ToolStatus(id="sqlmap"))
    aircrack_ng: ToolStatus = field(default_factory=lambda: ToolStatus(id="aircrack-ng"))


@dataclass
class VMCapabilityInfo:
    """Read-only VM/KVM capability evidence (Section 34/35) — never
    starts libvirtd, never creates a VM, never modifies groups."""

    kvm_device_present: bool = False
    kvm_module_loaded: bool = False
    qemu: ToolStatus = field(default_factory=lambda: ToolStatus(id="qemu-system-x86_64"))
    libvirt: ToolStatus = field(default_factory=lambda: ToolStatus(id="virsh"))
    #: True/False only from a real, read-only filesystem permission
    #: check on /dev/kvm (`os.access`, never opening/using the
    #: device); None when the device doesn't exist or can't be
    #: checked.
    user_access: bool | None = None


@dataclass
class CyberCapability:
    """Mirrors S4's ``AICapability`` shape exactly (Section 22, "reuse
    S4 capability semantics")."""

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
class CyberCapabilitiesReport:
    schema_version: int
    capabilities: list[CyberCapability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass
class CyberPlanAction:
    """Identical shape to S3/S4's plan action dataclasses (Section 26)."""

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
class CyberPlan:
    schema_version: int
    actions: list[CyberPlanAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class CyberStatusReport:
    schema_version: int
    profile_id: str
    profile_status: str
    network: NetworkDiagnosticsStatus
    capture: PacketCaptureStatus
    reverse: ReverseEngineeringStatus
    containers: CyberContainerStatusInfo
    vm: VMCapabilityInfo
    host_hygiene: HostHygieneStatus

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
