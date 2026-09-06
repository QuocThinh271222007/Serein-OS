"""Structured representations for the development subsystem.

Mirrors the pattern S2's ``hardware/models.py`` established: one models
module per subsystem, dataclasses only, no behavior. See
``docs/development/architecture.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEV_CAPABILITIES_SCHEMA_VERSION = 1
DEV_PLAN_SCHEMA_VERSION = 1

#: Independent of ``serein.__version__`` — bumped only when the shape of
#: a development config resource Serein ships changes in a way a future
#: migration needs to know about. See docs/development/architecture.md.
DEVELOPMENT_CONFIG_VERSION = 1

#: Where a tool comes from — see docs/development/package-strategy.md.
#: "ubuntu-repository": a real apt package in Ubuntu's own archive.
#: "official-upstream-repository": the vendor's own apt/package repo
#:   (e.g. GitHub CLI's), not Ubuntu's and not a third-party PPA.
#: "official-upstream-binary": a vendor-provided installer script or
#:   prebuilt binary (uv, rustup, fnm, pnpm, Zed) - never executed by S3.
#: "language-bootstrap-tool": a tool whose whole job is installing other
#:   tools/runtimes (rustup, fnm) - called out separately from a plain
#:   binary since its presence changes what "already provisioned" means.
#: "user-installed": detected but Serein did not request it - existing
#:   user tooling (e.g. a pre-existing pyenv/conda install).
#: "optional": not part of Serein's default plan; documented, not planned.
ToolSourceType = str  # Literal not used to keep JSON round-tripping simple


@dataclass(frozen=True)
class ToolDefinition:
    """One entry in the declarative package/tool manifest
    (``packages.py``) - data only, never executes anything."""

    id: str
    name: str
    source_type: ToolSourceType
    package: str | None  # apt package name, or None for non-APT tools
    requires_root: bool
    description: str


@dataclass
class ToolStatus:
    """Detection result for one tool. ``version`` is a free-form string
    parsed from the tool's own ``--version`` output - never a full path,
    never environment/user data."""

    id: str
    installed: bool = False
    version: str | None = None


@dataclass
class DevelopmentCapability:
    """Answers "can Serein safely provision/manage this stack" - distinct
    from ToolStatus's "does it already exist". Mirrors
    ``serein.hardware.models.Capability``'s shape exactly for CLI/schema
    consistency between the two subsystems."""

    id: str
    available: bool | None  # None = genuinely ambiguous, never guessed
    installed: bool
    mechanism: str | None
    source: str | None
    confidence: str  # "high" | "medium" | "low"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DevelopmentCapabilitiesReport:
    schema_version: int
    capabilities: list[DevelopmentCapability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass
class DevPlanAction:
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
class DevelopmentPlan:
    schema_version: int
    actions: list[DevPlanAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class GitStatusInfo:
    git: ToolStatus
    git_lfs: ToolStatus
    gh: ToolStatus


@dataclass
class PythonStatusInfo:
    system_python: ToolStatus
    uv: ToolStatus
    pyenv_present: bool = False
    conda_present: bool = False
    micromamba: ToolStatus = field(default_factory=lambda: ToolStatus(id="micromamba"))


@dataclass
class NodeStatusInfo:
    fnm: ToolStatus
    mise: ToolStatus
    nvm_present: bool
    node: ToolStatus
    pnpm: ToolStatus
    npm: ToolStatus

    @property
    def managers(self) -> tuple[str, ...]:
        """Detected Node version managers, in a stable order. Single
        source of truth for "which managers are present" - the planner
        and doctor both derive their conflict decisions from this
        instead of each re-enumerating fnm/mise/nvm independently."""
        detected = []
        if self.fnm.installed:
            detected.append("fnm")
        if self.mise.installed:
            detected.append("mise")
        if self.nvm_present:
            detected.append("nvm")
        return tuple(detected)

    @property
    def manager_count(self) -> int:
        return len(self.managers)


@dataclass
class RustStatusInfo:
    rustup: ToolStatus
    rustc: ToolStatus
    cargo: ToolStatus


@dataclass
class GoStatusInfo:
    go: ToolStatus


@dataclass
class CppStatusInfo:
    gcc: ToolStatus
    gpp: ToolStatus
    clang: ToolStatus
    cmake: ToolStatus
    ninja: ToolStatus
    gdb: ToolStatus
    lldb: ToolStatus
    pkg_config: ToolStatus
    strace: ToolStatus
    #: dpkg package-installation state for the ``build-essential``
    #: metapackage - deliberately not a ``ToolStatus`` (it owns no
    #: binary/version of its own) and never inferred from ``gcc``'s
    #: presence. See ``serein.development.dpkg``.
    build_essential_installed: bool = False


@dataclass
class EditorStatusInfo:
    zed: ToolStatus


@dataclass
class ContainerStatusInfo:
    podman: ToolStatus
    docker: ToolStatus
    distrobox: ToolStatus


@dataclass
class DevelopmentStatusReport:
    schema_version: int
    profile_id: str
    profile_status: str
    git: GitStatusInfo
    python: PythonStatusInfo
    node: NodeStatusInfo
    rust: RustStatusInfo
    go: GoStatusInfo
    cpp: CppStatusInfo
    editor: EditorStatusInfo
    containers: ContainerStatusInfo
