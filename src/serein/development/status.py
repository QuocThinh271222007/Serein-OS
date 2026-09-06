"""``serein dev status``: a read-only development-workstation summary.

Safe to run anywhere (Windows dev host, Ubuntu, WSL, CI, a container) —
every field degrades to an honest "unavailable" rather than raising.
Reuses the existing ``dev`` profile entry from the profile registry
(established in S2) rather than introducing a second profile concept.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.containers import detect_container_status
from serein.development.cpp import detect_cpp_status
from serein.development.editor import detect_editor_status
from serein.development.git import detect_git_status
from serein.development.go import detect_go_status
from serein.development.models import DevelopmentStatusReport
from serein.development.node import detect_node_status
from serein.development.python import detect_python_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.rust import detect_rust_status
from serein.profiles.registry import list_profiles


def build_development_status(
    runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> DevelopmentStatusReport:
    profiles = {p.id: p for p in list_profiles()}
    dev_profile = profiles.get("dev")

    return DevelopmentStatusReport(
        schema_version=1,
        profile_id="dev",
        profile_status=dev_profile.status if dev_profile else "declared",
        git=detect_git_status(runner),
        python=detect_python_status(runner, home),
        node=detect_node_status(runner, home),
        rust=detect_rust_status(runner),
        go=detect_go_status(runner),
        cpp=detect_cpp_status(runner),
        editor=detect_editor_status(runner, home),
        containers=detect_container_status(runner),
    )
