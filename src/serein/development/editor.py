"""Zed editor detection.

Zed's official Linux install method (``zed.dev/install.sh``) places the
binary under ``~/.local/`` and symlinks ``~/.local/bin/zed`` — that
directory is not guaranteed to be on every shell's ``$PATH``, so
detection falls back to the marker path when the plain ``--version``
probe fails. Never executes the installer. See
docs/development/editor-strategy.md.
"""

from __future__ import annotations

from pathlib import Path

from serein.development._util import default_home, marker_exists
from serein.development.models import EditorStatusInfo, ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_editor_status(
    runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> EditorStatusInfo:
    if home is None:
        home = default_home()

    zed = probe_tool("zed", "zed", runner=runner)
    if not zed.installed and marker_exists(home, ".local", "bin", "zed"):
        zed = ToolStatus(id="zed", installed=True, version=None)

    return EditorStatusInfo(zed=zed)
