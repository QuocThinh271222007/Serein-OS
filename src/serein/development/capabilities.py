"""``serein dev capabilities``: which development stacks Serein can
safely provision/manage — distinct from ``serein dev status`` (what
already exists). Reuses ``serein.hardware.environment`` (already
read-only/injectable) purely to detect a container-like context, since
nested container engines are the one real "this cannot work here" case
for a development capability — every language toolchain works fine
under WSL and inside a container for ordinary compilation/coding.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.containers import container_capability_available, detect_container_status
from serein.development.cpp import cpp_toolchain_fully_installed, detect_cpp_status
from serein.development.editor import detect_editor_status
from serein.development.git import detect_git_status
from serein.development.go import detect_go_status
from serein.development.models import DEV_CAPABILITIES_SCHEMA_VERSION, DevelopmentCapabilitiesReport
from serein.development.models import DevelopmentCapability as Capability
from serein.development.node import detect_node_status
from serein.development.python import detect_python_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.rust import detect_rust_status
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.environment import detect_environment


def build_development_capabilities(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> DevelopmentCapabilitiesReport:
    environment = detect_environment(root)
    git = detect_git_status(runner)
    python = detect_python_status(runner, home)
    node = detect_node_status(runner, home)
    rust = detect_rust_status(runner)
    go = detect_go_status(runner)
    cpp = detect_cpp_status(runner)
    editor = detect_editor_status(runner, home)
    containers = detect_container_status(runner)

    capabilities: list[Capability] = []

    capabilities.append(
        Capability(
            "git_cli", True, git.git.installed, "apt:git", "ubuntu-repository", "high",
            "Git is a standard Ubuntu package; always provisionable.",
        )
    )
    capabilities.append(
        Capability(
            "github_cli", True, git.gh.installed, "apt:gh", "ubuntu-repository", "high",
            "GitHub CLI is a standard Ubuntu package (older than GitHub's own apt "
            "repo - see docs/development/git-strategy.md).",
        )
    )
    capabilities.append(
        Capability(
            "python_uv", True, python.uv.installed, "official-upstream-binary",
            "official-upstream-binary", "high",
            "uv's official installer is a user-level binary; works identically under "
            "WSL and inside a container.",
        )
    )
    capabilities.append(
        Capability(
            "node_runtime", True, node.fnm.installed, "official-upstream-binary",
            "language-bootstrap-tool", "high",
            "fnm's official installer is a user-level binary; works identically under "
            "WSL and inside a container.",
        )
    )
    capabilities.append(
        Capability(
            "pnpm", True, node.pnpm.installed, "official-upstream-binary",
            "official-upstream-binary", "high",
            "pnpm's standalone installer is user-level; does not require Corepack.",
        )
    )
    capabilities.append(
        Capability(
            "rustup", True, rust.rustup.installed, "official-upstream-binary",
            "language-bootstrap-tool", "high",
            "rustup's official installer is user-level; works identically under WSL "
            "and inside a container.",
        )
    )
    capabilities.append(
        Capability(
            "go_toolchain", True, go.go.installed, "apt:golang-go",
            "ubuntu-repository", "high",
            "Go is a standard Ubuntu package close enough to upstream's own cadence.",
        )
    )
    capabilities.append(
        Capability(
            "cpp_toolchain", True, cpp_toolchain_fully_installed(cpp),
            "apt:build-essential,clang,cmake,ninja-build,gdb,lldb",
            "ubuntu-repository", "high",
            "The full C/C++ toolchain is standard Ubuntu packages.",
        )
    )
    capabilities.append(
        Capability(
            "zed_editor", True, editor.zed.installed, "official-upstream-binary",
            "official-upstream-binary", "medium",
            "Zed's official installer is a user-level binary; installable anywhere, "
            "though a GUI session is required to actually run it (not verifiable "
            "here - see docs/development/editor-strategy.md).",
        )
    )

    container_available = container_capability_available(environment)
    container_engine_installed = containers.podman.installed or containers.docker.installed
    if not container_available:
        capabilities.append(
            Capability(
                "container_engine", False, container_engine_installed,
                None, "ubuntu-repository", "high",
                "Running inside a container: a nested container engine is unusual and "
                "often unsupported. Serein does not plan one here.",
            )
        )
        capabilities.append(
            Capability(
                "distrobox", False, containers.distrobox.installed, None, "ubuntu-repository",
                "high", "Distrobox requires a container engine backend, unavailable in "
                "this nested-container context.",
            )
        )
    else:
        capabilities.append(
            Capability(
                "container_engine", True,
                containers.podman.installed or containers.docker.installed, "apt:podman",
                "ubuntu-repository", "high",
                "Podman is a standard Ubuntu package and rootless by default.",
            )
        )
        capabilities.append(
            Capability(
                "distrobox", True, containers.distrobox.installed, "apt:distrobox",
                "ubuntu-repository", "high",
                "Distrobox is a standard Ubuntu package, pairs with Podman.",
            )
        )

    return DevelopmentCapabilitiesReport(
        schema_version=DEV_CAPABILITIES_SCHEMA_VERSION, capabilities=capabilities
    )
