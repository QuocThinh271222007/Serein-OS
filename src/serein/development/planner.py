"""``serein dev plan [component]``: deterministic, evidence-based
development-workstation planning.

No Apply mechanism exists in S3 (see docs/development/architecture.md) —
this module only ever reads state (via the ``serein.development.*``
detectors) and proposes ``DevPlanAction``s with an explicit ``status`` of
``APPLY``/``NOOP``/``SKIP``/``BLOCKED``. Nothing here writes a package,
runs an installer script, or touches ``~/.gitconfig``/``~/.config/zed``.
A plan is a pure function of on-disk/PATH state: calling it twice
produces identical output.

Component filtering (``serein dev plan python``) filters the one
canonical action list built here — it is never a separately-derived
plan, per docs/development/architecture.md.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.containers import container_capability_available, detect_container_status
from serein.development.cpp import cpp_installed_map, detect_cpp_status
from serein.development.editor import detect_editor_status
from serein.development.git import detect_git_status
from serein.development.go import detect_go_status
from serein.development.models import (
    DEV_PLAN_SCHEMA_VERSION,
    ContainerStatusInfo,
    CppStatusInfo,
    DevelopmentPlan,
    DevPlanAction,
    EditorStatusInfo,
    GitStatusInfo,
    GoStatusInfo,
    NodeStatusInfo,
    PythonStatusInfo,
    RustStatusInfo,
    ToolDefinition,
)
from serein.development.node import detect_node_status
from serein.development.packages import (
    BASE_TOOLS,
    CLI_PRODUCTIVITY_TOOLS,
    CPP_TOOLS,
    GIT_TOOLS,
    GO_TOOLS,
)
from serein.development.python import detect_python_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.rust import detect_rust_status
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment
from serein.hardware.models import EnvironmentInfo

VALID_COMPONENTS: tuple[str, ...] = (
    "base", "git", "python", "node", "rust", "go", "cpp", "containers", "editor",
)


def _apt_group_action(
    action_id: str,
    component: str,
    tools: tuple[ToolDefinition, ...],
    installed_ids: set[str],
) -> DevPlanAction:
    missing = [t for t in tools if t.id not in installed_ids]
    tool_names = ", ".join(t.package or t.id for t in tools)
    verify = f"dpkg -s {' '.join(t.package for t in tools if t.package)} 2>&1 | grep Status"
    if not missing:
        return DevPlanAction(
            action_id, component, "install_apt_packages", tool_names, "ubuntu-repository",
            "installed", "installed", "All packages in this group are already installed.",
            False, True, "none", verify, "NOOP",
        )
    missing_names = ", ".join(t.package or t.id for t in missing)
    return DevPlanAction(
        action_id, component, "install_apt_packages", tool_names, "ubuntu-repository",
        "partially installed" if len(missing) < len(tools) else "not installed",
        tool_names, f"Missing package(s): {missing_names}.", True, True, "low", verify, "APPLY",
    )


def _base_action() -> DevPlanAction:
    tools = list(BASE_TOOLS) + list(CLI_PRODUCTIVITY_TOOLS)
    # Base tools are common enough (curl, git dependencies, etc.) that S3
    # does not probe each one individually here - the group is planned as
    # a whole; a per-package doctor check exists for finer-grained state.
    return DevPlanAction(
        "base.apt_packages", "base", "install_apt_packages",
        ", ".join(t.package or t.id for t in tools), "ubuntu-repository", "unknown",
        ", ".join(t.package or t.id for t in tools),
        "Baseline CLI/productivity tools for a development workstation.",
        True, True, "low", "dpkg -s <package> 2>&1 | grep Status", "APPLY",
    )


def _git_action(git_status: GitStatusInfo) -> DevPlanAction:
    installed = {t.id for t in GIT_TOOLS if getattr(git_status, t.id.replace("-", "_")).installed}
    return _apt_group_action("git.apt_packages", "git", GIT_TOOLS, installed)


def _python_uv_action(python_status: PythonStatusInfo) -> DevPlanAction:
    if python_status.uv.installed:
        return DevPlanAction(
            "python.uv", "python", "install_tool", "uv", "official-upstream-binary",
            python_status.uv.version, python_status.uv.version,
            "uv is already installed; the system Python (owned by Ubuntu) is never "
            "a mutation target.",
            False, True, "none", "uv --version", "NOOP",
        )
    return DevPlanAction(
        "python.uv", "python", "install_tool", "uv", "official-upstream-binary",
        "not installed", "latest",
        "Serein prefers uv for project-local Python environments; the system Python "
        "(owned by Ubuntu) is never touched. Official installer: astral.sh/uv/install.sh "
        "(not executed by S3 - see docs/development/python-strategy.md).",
        False, True, "low", "uv --version", "APPLY",
    )


def _python_conflict_action(python_status: PythonStatusInfo) -> DevPlanAction:
    existing: list[str] = []
    if python_status.pyenv_present:
        existing.append("pyenv")
    if python_status.conda_present:
        existing.append("conda")
    if python_status.micromamba.installed:
        existing.append("micromamba")
    detail = (
        f"Existing Python tooling detected ({', '.join(existing)}); Serein does not "
        "remove or replace it. uv is offered for new projects only."
        if existing
        else "No other Python environment manager detected."
    )
    return DevPlanAction(
        "python.existing_managers", "python", "report_only", "pyenv/conda/micromamba", None,
        ", ".join(existing) if existing else "none", None, detail, False, True, "none", "n/a",
        "NOOP",
    )


def _node_manager_conflict(node_status: NodeStatusInfo) -> bool:
    """True when Node runtime ownership is ambiguous: more than one
    manager present, or exactly one manager present that isn't fnm.
    Single source of truth shared by ``_node_manager_action`` and
    ``_pnpm_action`` (S3R corrective - see docs/development/
    node-strategy.md's "Node manager conflict state machine")."""
    managers = node_status.managers
    if len(managers) > 1:
        return True
    return len(managers) == 1 and not node_status.fnm.installed


def _node_manager_action(node_status: NodeStatusInfo) -> DevPlanAction:
    action_id, component, action = "node.manager", "node", "install_tool"
    managers = node_status.managers
    if len(managers) > 1:
        detected = ", ".join(managers)
        return DevPlanAction(
            action_id, component, action, "fnm", "language-bootstrap-tool",
            detected, "fnm",
            f"Multiple Node version managers are already present ({detected}). "
            "Serein will not select, remove, or layer another manager until the "
            "user chooses which existing manager should own Node runtime "
            "management.",
            False, True, "none", "n/a", "BLOCKED",
        )
    if len(managers) == 1 and not node_status.fnm.installed:
        other = managers[0]
        return DevPlanAction(
            action_id, component, action, "fnm", "language-bootstrap-tool",
            other, "fnm",
            f"An existing Node version manager ({other}) is already present. "
            "Serein will not layer fnm on top of it; choose which manager "
            "should own Node runtime management before Serein provisions "
            "another.",
            False, True, "none", "n/a", "BLOCKED",
        )
    if node_status.fnm.installed:
        return DevPlanAction(
            action_id, component, action, "fnm", "language-bootstrap-tool",
            node_status.fnm.version, node_status.fnm.version,
            "fnm is already installed.", False, True, "none", "fnm --version", "NOOP",
        )
    return DevPlanAction(
        action_id, component, action, "fnm", "language-bootstrap-tool",
        "not installed", "latest",
        "No Node version manager detected. fnm is Serein's preferred choice (fast, "
        "single-purpose, actively maintained - see ADR-0010). Official installer: "
        "fnm.vercel.app/install (not executed by S3).",
        False, True, "low", "fnm --version", "APPLY",
    )


def _pnpm_action(node_status: NodeStatusInfo) -> DevPlanAction:
    if node_status.pnpm.installed:
        return DevPlanAction(
            "node.pnpm", "node", "install_tool", "pnpm", "official-upstream-binary",
            node_status.pnpm.version, node_status.pnpm.version,
            "pnpm is already installed.", False, True, "none", "pnpm --version", "NOOP",
        )
    if _node_manager_conflict(node_status):
        return DevPlanAction(
            "node.pnpm", "node", "install_tool", "pnpm", "official-upstream-binary",
            "not installed", None,
            "Node runtime management is unresolved (see node.manager); Serein "
            "will not provision pnpm until an existing or chosen Node manager "
            "owns the Node runtime, to avoid adding a second ambiguous "
            "PATH/config source on top of an already-ambiguous Node setup.",
            False, True, "none", "n/a", "BLOCKED",
        )
    return DevPlanAction(
        "node.pnpm", "node", "install_tool", "pnpm", "official-upstream-binary",
        "not installed", "latest",
        "pnpm is Serein's preferred Node package manager. Installed via pnpm's own "
        "standalone installer (get.pnpm.io/install.sh), not Corepack (being removed "
        "from Node - see docs/development/node-strategy.md). npm remains available "
        "with Node and is never removed.",
        False, True, "low", "pnpm --version", "APPLY",
    )


def _rust_action(rust_status: RustStatusInfo) -> DevPlanAction:
    action_id, component, action = "rust.rustup", "rust", "install_tool"
    if rust_status.rustup.installed:
        return DevPlanAction(
            action_id, component, action, "rustup", "language-bootstrap-tool",
            rust_status.rustup.version, rust_status.rustup.version,
            "rustup is already installed; Serein will not reinstall it.",
            False, True, "none", "rustup --version", "NOOP",
        )
    if rust_status.rustc.installed or rust_status.cargo.installed:
        return DevPlanAction(
            action_id, component, action, "rustup", "language-bootstrap-tool",
            "distro Rust detected", "latest",
            "An existing (likely distro-packaged) Rust toolchain was detected without "
            "rustup. Serein's policy prefers rustup for a current, easily-updated "
            "toolchain; rustup installs additively into ~/.cargo and does not remove "
            "the existing installation.",
            False, True, "low", "rustup --version", "APPLY",
        )
    return DevPlanAction(
        action_id, component, action, "rustup", "language-bootstrap-tool",
        "not installed", "stable",
        "No Rust toolchain detected. Official installer: rustup.rs (not executed by "
        "S3). Installs stable rustc/cargo/rustfmt/clippy - no nightly by default.",
        False, True, "low", "rustup --version", "APPLY",
    )


def _go_action(go_status: GoStatusInfo) -> DevPlanAction:
    if go_status.go.installed:
        return DevPlanAction(
            "go.toolchain", "go", "install_apt_packages", "golang-go", "ubuntu-repository",
            go_status.go.version, go_status.go.version,
            "A Go toolchain is already installed; Serein will not install a second "
            "Go tree or modify the existing one.",
            False, True, "none", "go version", "NOOP",
        )
    return _apt_group_action("go.toolchain", "go", GO_TOOLS, set())


def _cpp_action(cpp_status: CppStatusInfo) -> DevPlanAction:
    installed_map = cpp_installed_map(cpp_status)
    installed_ids = {t.id for t in CPP_TOOLS if installed_map.get(t.package or "", False)}
    return _apt_group_action("cpp.toolchain", "cpp", CPP_TOOLS, installed_ids)


def _editor_action(editor_status: EditorStatusInfo) -> DevPlanAction:
    if editor_status.zed.installed:
        return DevPlanAction(
            "editor.zed", "editor", "install_tool", "zed", "official-upstream-binary",
            editor_status.zed.version or "installed", editor_status.zed.version or "installed",
            "Zed is already installed.", False, True, "none", "zed --version", "NOOP",
        )
    return DevPlanAction(
        "editor.zed", "editor", "install_tool", "zed", "official-upstream-binary",
        "not installed", "latest",
        "Zed is Serein's preferred editor. Official installer: zed.dev/install.sh "
        "(not executed by S3 - see docs/development/editor-strategy.md). A "
        "recommended settings template ships at development/zed/settings.json, "
        "applied only to a user with no existing Zed settings file.",
        False, True, "low", "zed --version", "APPLY",
    )


def _containers_action(
    container_status: ContainerStatusInfo, environment: EnvironmentInfo
) -> DevPlanAction:
    action_id, component, action = "containers.engine", "containers", "install_apt_packages"
    if not container_capability_available(environment):
        return DevPlanAction(
            action_id, component, action, "podman", "ubuntu-repository", "not applicable",
            None,
            "Running inside a container: Serein does not plan a nested container "
            "engine here.",
            False, True, "none", "n/a", "SKIP",
        )
    if container_status.podman.installed or container_status.docker.installed:
        engines = []
        if container_status.podman.installed:
            engines.append("podman")
        if container_status.docker.installed:
            engines.append("docker")
        return DevPlanAction(
            action_id, component, action, "podman", "ubuntu-repository", ", ".join(engines),
            ", ".join(engines),
            f"Container engine(s) already present ({', '.join(engines)}); Serein will "
            "not install a competing engine.",
            False, True, "none", "podman --version || docker --version", "NOOP",
        )
    return DevPlanAction(
        action_id, component, action, "podman", "ubuntu-repository", "not installed", "podman",
        "No container engine detected. Podman is Serein's preferred default: "
        "rootless by default, pairs with Distrobox (see ADR-0011).",
        True, True, "low", "podman --version", "APPLY",
    )


def _distrobox_action(
    container_status: ContainerStatusInfo, environment: EnvironmentInfo
) -> DevPlanAction:
    action_id, component, action = "containers.distrobox", "containers", "install_apt_packages"
    if not container_capability_available(environment):
        return DevPlanAction(
            action_id, component, action, "distrobox", "ubuntu-repository", "not applicable",
            None,
            "Running inside a container: Distrobox needs a container engine backend, "
            "unavailable in this nested-container context.",
            False, True, "none", "n/a", "SKIP",
        )
    if container_status.distrobox.installed:
        return DevPlanAction(
            action_id, component, action, "distrobox", "ubuntu-repository",
            container_status.distrobox.version, container_status.distrobox.version,
            "Distrobox is already installed.", False, True, "none", "distrobox --version",
            "NOOP",
        )
    return DevPlanAction(
        action_id, component, action, "distrobox", "ubuntu-repository", "not installed",
        "distrobox",
        "Distrobox is a standard Ubuntu package; pairs with Podman for isolated "
        "development sandboxes and future tool isolation (Cyber Toolbox in S5).",
        True, True, "low", "distrobox --version", "APPLY",
    )


def build_development_plan(
    component: str | None = None,
    root: Path = DEFAULT_ROOT,
    runner: CommandRunner = DEFAULT_RUNNER,
    home: Path | None = None,
) -> DevelopmentPlan:
    if component is not None and component not in VALID_COMPONENTS:
        raise ValueError(f"unknown development component: {component!r}")

    environment = detect_environment(root)
    git_status = detect_git_status(runner)
    python_status = detect_python_status(runner, home)
    node_status = detect_node_status(runner, home)
    rust_status = detect_rust_status(runner)
    go_status = detect_go_status(runner)
    cpp_status = detect_cpp_status(runner)
    editor_status = detect_editor_status(runner, home)
    container_status = detect_container_status(runner)

    actions = [
        _base_action(),
        _git_action(git_status),
        _python_uv_action(python_status),
        _python_conflict_action(python_status),
        _node_manager_action(node_status),
        _pnpm_action(node_status),
        _rust_action(rust_status),
        _go_action(go_status),
        _cpp_action(cpp_status),
        _containers_action(container_status, environment),
        _distrobox_action(container_status, environment),
        _editor_action(editor_status),
    ]

    if component is not None:
        actions = [a for a in actions if a.component == component]

    return DevelopmentPlan(schema_version=DEV_PLAN_SCHEMA_VERSION, actions=actions)
