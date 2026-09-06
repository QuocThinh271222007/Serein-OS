"""Python environment detection.

The system Python (``python3``) is Ubuntu-owned and never a mutation
target — this module only ever reads its version. Existing
pyenv/conda/micromamba installs are detected and reported, never
deleted or replaced; ``uv`` is Serein's preferred tool for *new* project
environments, which does not require removing anything a user already
has. See docs/development/python-strategy.md.
"""

from __future__ import annotations

from pathlib import Path

from serein.development._util import default_home, marker_exists
from serein.development.models import PythonStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def _detect_conda_present(runner: CommandRunner, home: Path) -> bool:
    if probe_tool("conda", "conda", runner=runner).installed:
        return True
    return marker_exists(home, "miniconda3") or marker_exists(home, "anaconda3")


def detect_python_status(
    runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> PythonStatusInfo:
    if home is None:
        home = default_home()

    return PythonStatusInfo(
        system_python=probe_tool("system_python", "python3", runner=runner),
        uv=probe_tool("uv", "uv", runner=runner),
        pyenv_present=marker_exists(home, ".pyenv"),
        conda_present=_detect_conda_present(runner, home),
        micromamba=probe_tool("micromamba", "micromamba", runner=runner),
    )
