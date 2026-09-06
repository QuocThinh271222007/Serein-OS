"""Go toolchain detection.

Ubuntu 26.04's ``golang-go`` package (verified: 1.26.0, see
docs/validation/s3/package-validation.md) is Serein's preferred source —
close enough to upstream's own release cadence to not warrant a second
version-management layer. See docs/development/go-strategy.md.
"""

from __future__ import annotations

from serein.development.models import GoStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_go_status(runner: CommandRunner = DEFAULT_RUNNER) -> GoStatusInfo:
    return GoStatusInfo(go=probe_tool("go", "go", runner=runner))
