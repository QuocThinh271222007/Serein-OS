"""Serein Cyber's declarative tool classification manifest.

Every tool has exactly ONE canonical ``recommended_tier`` (Section 62)
— never a second, independently-derived classification that could
drift. This module is plain data: nothing here executes a package
manager, a container command, or a VM operation. Package names were
verified against the real Ubuntu 26.04 archive in a disposable,
isolated environment — see docs/validation/s5/ubuntu-package-validation.md.

Tier reasoning follows the S5 brief's own three-tier model
(Section 5): Host / Cyber Light for safe, high-value diagnostics;
Isolated Cyber Toolbox for specialized/dependency-heavy/potentially
conflicting tooling (Distrobox + Podman, reusing S3's container
architecture unchanged); VM / Full Isolation for untrusted binaries,
full offensive environments, and anything that would need broad
host privileges to be useful.
"""

from __future__ import annotations

from serein.cyber.models import CyberToolDefinition

# --- Tier 1: Host / Cyber Light -------------------------------------------

HOST_NETWORK_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "nmap", "Nmap", "network-diagnostics", "ubuntu-repository", "nmap",
        "host", True, False, True, "low",
        "Authorized network diagnostics/discovery. Detection and installation "
        "planning only - Serein never invokes nmap against any target "
        "(see docs/cyber/security-boundaries.md).",
    ),
    CyberToolDefinition(
        "tcpdump", "tcpdump", "packet-capture", "ubuntu-repository", "tcpdump",
        "host", True, True, True, "low",
        "CLI packet capture - requires CAP_NET_RAW at runtime like any "
        "capture tool; Serein never runs a live capture (Section 7/8).",
    ),
    CyberToolDefinition(
        "bind9-dnsutils", "dnsutils (dig)", "network-diagnostics", "ubuntu-repository",
        "bind9-dnsutils", "host", True, False, True, "none",
        "DNS diagnostics (dig/nslookup) - read-only local tooling. Package "
        "name is bind9-dnsutils, not the older transitional 'dnsutils' name "
        "(removed on Ubuntu 26.04 - see docs/validation/s5/package-validation.md).",
    ),
    CyberToolDefinition(
        "whois", "whois", "network-diagnostics", "ubuntu-repository", "whois",
        "host", True, False, True, "none",
        "WHOIS lookups - a normal diagnostic utility.",
    ),
    CyberToolDefinition(
        "openssl", "OpenSSL", "network-diagnostics", "ubuntu-repository", "openssl",
        "host", True, False, True, "none",
        "TLS/crypto diagnostics (s_client, x509 inspection) - already a "
        "base OS dependency on any Ubuntu host.",
    ),
    CyberToolDefinition(
        "socat", "socat", "network-diagnostics", "ubuntu-repository", "socat",
        "host", True, False, True, "low",
        "General-purpose socket relay/diagnostic tool.",
    ),
    CyberToolDefinition(
        "netcat-openbsd", "netcat (OpenBSD)", "network-diagnostics",
        "ubuntu-repository", "netcat-openbsd", "host", True, False, True, "low",
        "The OpenBSD netcat variant - Ubuntu's default/preferred nc "
        "implementation, not the traditional or ncat variants.",
    ),
    CyberToolDefinition(
        "mtr-tiny", "mtr", "network-diagnostics", "ubuntu-repository", "mtr-tiny",
        "host", True, False, True, "none",
        "Combined ping/traceroute diagnostic - the CLI-only package "
        "variant (no GUI dependency).",
    ),
    CyberToolDefinition(
        "ethtool", "ethtool", "network-diagnostics", "ubuntu-repository", "ethtool",
        "host", True, False, True, "none",
        "NIC diagnostics/settings inspection - read-only query use is "
        "the only thing Serein documents; ethtool can also mutate "
        "interface settings, which Serein never does.",
    ),
)

HOST_CAPTURE_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "tshark", "tshark", "packet-capture", "ubuntu-repository", "tshark",
        "host", True, True, True, "low",
        "CLI-only Wireshark analysis engine - preferred over the GUI "
        "wireshark package for headless/server hosts (Section 38). "
        "Capture privilege is a separate, real-evidence-based question "
        "- see docs/cyber/packet-capture.md.",
    ),
    CyberToolDefinition(
        "wireshark", "Wireshark", "packet-capture", "ubuntu-repository", "wireshark",
        "host", True, True, True, "low",
        "GUI packet analysis - fully appropriate to have on a desktop "
        "host (recommended_tier=host), but NOT part of Serein's default "
        "install baseline (default_install=False): live validation found "
        "installing the full GUI package pulls a complete Qt6/GTK "
        "dependency stack (169 packages resolved vs. 48 for tshark alone "
        "- see docs/validation/s5/package-validation.md Finding 2), and "
        "tshark/wireshark-common already supply the compact default "
        "CLI-safe capture stack (Section 38/37). A user who wants the "
        "GUI may still install it; Serein just never forces its weight "
        "onto every host by default. Serein never mutates dumpcap's "
        "file capabilities or group membership to enable capture.",
        default_install=False,
    ),
)

HOST_REVERSE_ENGINEERING_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "file", "file", "reverse-engineering", "ubuntu-repository", "file",
        "host", True, False, True, "none",
        "File-type identification - a normal, ubiquitous OS utility.",
    ),
    CyberToolDefinition(
        "binutils", "binutils", "reverse-engineering", "ubuntu-repository", "binutils",
        "host", True, False, True, "none",
        "readelf/objdump/nm/strings - already a common build-toolchain "
        "dependency (overlaps with S3's C/C++ baseline).",
    ),
)

HOST_FORENSICS_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "exiftool", "ExifTool", "forensics", "ubuntu-repository", "libimage-exiftool-perl",
        "host", True, False, True, "none",
        "Metadata inspection for a single file the user provides - not "
        "a filesystem/device forensic collection tool.",
    ),
)

# --- Tier 2: Isolated Cyber Toolbox ----------------------------------------

TOOLBOX_RECON_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "masscan", "masscan", "network-diagnostics", "ubuntu-repository", "masscan",
        "toolbox", True, True, True, "medium",
        "High-rate port scanner - specialized, high-network-privilege "
        "tool; kept out of the host baseline even though Ubuntu "
        "packages it, per the toolbox-isolation policy.",
    ),
)

TOOLBOX_WEB_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "mitmproxy", "mitmproxy", "web-security", "python-package-index", "mitmproxy",
        "toolbox", False, False, True, "low",
        "TLS-intercepting proxy - installed via uv into an isolated "
        "environment/toolbox, never system Python (Section 42/43). Ubuntu "
        "26.04 does carry an apt package (8.1.1-4, live-confirmed), but it "
        "is significantly stale against upstream's current 12.2.3 release "
        "(a 4-major-version gap spanning substantial HTTP/addon-API "
        "changes) - a deliberate exception to the 'prefer apt when "
        "reasonably current' default (S5R Section 24/26), not inertia.",
    ),
    CyberToolDefinition(
        "burpsuite", "Burp Suite Community", "web-security", "optional", None,
        "user-managed", False, False, True, "low",
        "Proprietary installer/license flow - Serein never automates "
        "acceptance of a proprietary EULA or downloads the installer "
        "(Section 40). Documented as user-managed, GUI, toolbox-hosted.",
    ),
    CyberToolDefinition(
        "zaproxy", "OWASP ZAP", "web-security", "official-upstream-binary", None,
        "toolbox", False, False, True, "low",
        "Official upstream release (current mechanism verified - see "
        "docs/validation/s5/ubuntu-package-validation.md); GUI-primary, "
        "toolbox-hosted (Section 41).",
    ),
    CyberToolDefinition(
        "ffuf", "ffuf", "web-security", "ubuntu-repository", "ffuf",
        "toolbox", True, False, True, "low",
        "Web fuzzing tool - real, reasonably current Ubuntu 26.04 package "
        "(2.1.0-1build1 vs. upstream's current 2.2.1 - one minor release "
        "behind, live-confirmed), preferred over an upstream Go-binary "
        "install to reduce supply-chain complexity (S5R Section 26); "
        "toolbox-tier, not host, regardless of source.",
    ),
    CyberToolDefinition(
        "gobuster", "gobuster", "web-security", "ubuntu-repository", "gobuster",
        "toolbox", True, False, True, "low",
        "Content/DNS bruteforce tool - real Ubuntu 26.04 package "
        "(3.8.2-1) exactly matching upstream's current v3.8.2 release, "
        "live-confirmed; preferred over an upstream Go-binary install "
        "(S5R Section 26). Toolbox-tier, not host.",
    ),
    CyberToolDefinition(
        "nikto", "Nikto", "web-security", "official-upstream-binary", None,
        "toolbox", False, False, True, "medium",
        "Web server scanner - active-scanning tool, toolbox only.",
    ),
    CyberToolDefinition(
        "sqlmap", "sqlmap", "web-security", "ubuntu-repository", "sqlmap",
        "toolbox", True, False, True, "high",
        "Automated SQL injection tool - toolbox only, never host "
        "baseline (Section 12). Real Ubuntu 26.04 package (1.10.4-1, "
        "live-confirmed); upstream sqlmap has no frequent tagged release "
        "beyond its last 1.10 tag and is otherwise developed continuously "
        "on its master branch, so Ubuntu's packaged snapshot is preferred "
        "over an ad hoc git-clone-of-master install (S5R Section 26/30).",
    ),
)

TOOLBOX_PASSWORD_AUDIT_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "hashcat", "hashcat", "password-audit", "ubuntu-repository", "hashcat",
        "toolbox", True, False, True, "high",
        "GPU-accelerated password/hash cracking - never host baseline "
        "(Section 15); Serein classifies source/capability only, never "
        "implements a cracking workflow.",
    ),
    CyberToolDefinition(
        "john", "John the Ripper", "password-audit", "ubuntu-repository", "john",
        "toolbox", True, False, True, "high",
        "Password cracking - toolbox only.",
    ),
    CyberToolDefinition(
        "hydra", "THC-Hydra", "password-audit", "ubuntu-repository", "hydra",
        "toolbox", True, True, True, "high",
        "Network login brute-forcer - toolbox only; Serein never runs "
        "credential-spraying workflows (Section 3).",
    ),
)

TOOLBOX_EXPLOIT_DEV_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "metasploit-framework", "Metasploit Framework", "exploit-framework",
        "official-upstream-repository", None, "toolbox", True, True, True, "high",
        "Exploit framework - toolbox or VM depending on workload, never "
        "host baseline. Serein never executes an exploit or downloads "
        "module updates (Section 16).",
    ),
    CyberToolDefinition(
        "pwntools", "pwntools", "exploit-framework", "python-package-index", "pwntools",
        "toolbox", False, False, True, "medium",
        "CTF/exploit-dev Python library - uv-managed environment or "
        "toolbox, never system Python.",
    ),
)

TOOLBOX_WIRELESS_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "aircrack-ng", "aircrack-ng", "wireless", "ubuntu-repository", "aircrack-ng",
        "toolbox", True, True, True, "high",
        "Wireless auditing suite - requires monitor-mode-capable "
        "hardware/drivers and CAP_NET_ADMIN; Serein only models this "
        "requirement, never enables monitor mode/deauth/handshake "
        "capture (Section 17).",
    ),
)

TOOLBOX_FORENSICS_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "sleuthkit", "The Sleuth Kit", "forensics", "ubuntu-repository", "sleuthkit",
        "toolbox", True, False, True, "medium",
        "Filesystem/disk forensic toolkit - toolbox, not host; Serein "
        "never inspects disks/devices/filesystems for evidence "
        "(Section 69).",
    ),
    CyberToolDefinition(
        "binwalk", "binwalk", "forensics", "ubuntu-repository", "binwalk",
        "toolbox", True, False, True, "low",
        "Firmware/binary analysis - toolbox by default (heavier "
        "dependency footprint than the host RE baseline).",
    ),
)

TOOLBOX_REVERSE_ENGINEERING_TOOLS: tuple[CyberToolDefinition, ...] = (
    CyberToolDefinition(
        "radare2", "radare2", "reverse-engineering", "ubuntu-repository", "radare2",
        "toolbox", True, False, True, "low",
        "Full RE framework - real Ubuntu package (verified live), but "
        "classified toolbox by default given its size/dependency "
        "footprint relative to the compact host RE baseline; a user "
        "may reasonably install it on host too (risk is low either way).",
    ),
    CyberToolDefinition(
        "ghidra", "Ghidra", "reverse-engineering", "official-upstream-binary", None,
        "toolbox", False, False, True, "low",
        "No Ubuntu archive package (verified live - see "
        "docs/validation/s5/ubuntu-package-validation.md); official "
        "upstream release archive (NSA/ghidra-sre.org GitHub Releases), "
        "self-contained, no installer to execute. Toolbox/user-managed.",
    ),
)

# --- All groups -------------------------------------------------------------

ALL_GROUPS: tuple[tuple[str, tuple[CyberToolDefinition, ...]], ...] = (
    ("host-network", HOST_NETWORK_TOOLS),
    ("host-capture", HOST_CAPTURE_TOOLS),
    ("host-reverse-engineering", HOST_REVERSE_ENGINEERING_TOOLS),
    ("host-forensics", HOST_FORENSICS_TOOLS),
    ("toolbox-recon", TOOLBOX_RECON_TOOLS),
    ("toolbox-web", TOOLBOX_WEB_TOOLS),
    ("toolbox-password-audit", TOOLBOX_PASSWORD_AUDIT_TOOLS),
    ("toolbox-exploit-dev", TOOLBOX_EXPLOIT_DEV_TOOLS),
    ("toolbox-wireless", TOOLBOX_WIRELESS_TOOLS),
    ("toolbox-forensics", TOOLBOX_FORENSICS_TOOLS),
    ("toolbox-reverse-engineering", TOOLBOX_REVERSE_ENGINEERING_TOOLS),
)


def all_tools() -> list[CyberToolDefinition]:
    """Every declared cyber tool across every group - deduplicated by id."""
    seen: set[str] = set()
    result: list[CyberToolDefinition] = []
    for _group_name, tools in ALL_GROUPS:
        for tool in tools:
            if tool.id not in seen:
                seen.add(tool.id)
                result.append(tool)
    return result


def host_tools() -> list[CyberToolDefinition]:
    """Every tool appropriate to have on the host, IF the user chooses
    it. Not the same as the default install set - see
    ``default_host_tools()`` (S5R Section 10: tier != default)."""
    return [t for t in all_tools() if t.recommended_tier == "host"]


def default_host_tools() -> list[CyberToolDefinition]:
    """The strict subset of ``host_tools()`` Serein actually installs
    by default (``default_install=True``) - e.g. Wireshark's GUI is
    ``recommended_tier="host"`` (appropriate to have) but
    ``default_install=False`` (not forced onto every host). This is the
    single canonical source both the planner and the profile manifest
    must derive from (Section 12-13) - never duplicated independently."""
    return [t for t in host_tools() if t.default_install]


def toolbox_tools() -> list[CyberToolDefinition]:
    return [t for t in all_tools() if t.recommended_tier == "toolbox"]


def default_apt_packages() -> list[str]:
    """Every apt package Serein's *default* host-tier manifest
    requests, deduplicated and sorted - mirrors S3/S4's own
    ``default_apt_packages()`` shape. Only default-install,
    ubuntu-repository host-tier tools contribute - toolbox/VM/
    user-managed tools, and host-tier-but-optional tools (Wireshark
    GUI), are documented but never part of a default host install."""
    seen: set[str] = set()
    result: list[str] = []
    for tool in default_host_tools():
        if tool.source_type == "ubuntu-repository" and tool.package and tool.package not in seen:
            seen.add(tool.package)
            result.append(tool.package)
    return sorted(result)
