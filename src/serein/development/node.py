"""Node.js environment detection.

``nvm`` is a shell function sourced from ``~/.nvm/nvm.sh``, not a real
executable — it cannot be probed via a subprocess version check, so its
presence is detected as a filesystem marker instead (the directory
existing, never its contents). ``fnm`` (Serein's preferred manager) and
``mise`` are real binaries. See docs/development/node-strategy.md for
why fnm was chosen over nvm/mise and the resulting conflict policy.
"""

from __future__ import annotations

from pathlib import Path

from serein.development._util import default_home, marker_exists
from serein.development.models import NodeStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_node_status(
    runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> NodeStatusInfo:
    if home is None:
        home = default_home()

    return NodeStatusInfo(
        fnm=probe_tool("fnm", "fnm", runner=runner),
        mise=probe_tool("mise", "mise", runner=runner),
        nvm_present=marker_exists(home, ".nvm", "nvm.sh"),
        node=probe_tool("node", "node", runner=runner),
        pnpm=probe_tool("pnpm", "pnpm", runner=runner),
        npm=probe_tool("npm", "npm", runner=runner),
    )
