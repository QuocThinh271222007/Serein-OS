"""Git / GitHub CLI detection.

Never reads ``~/.gitconfig`` (name/email/signing key), never inspects
credential helpers, never touches SSH keys — detection is limited to
"is the binary present and what version" via ``--version``. See
docs/development/git-strategy.md.
"""

from __future__ import annotations

from serein.development.models import GitStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_git_status(runner: CommandRunner = DEFAULT_RUNNER) -> GitStatusInfo:
    return GitStatusInfo(
        git=probe_tool("git", "git", runner=runner),
        git_lfs=probe_tool("git-lfs", "git-lfs", runner=runner),
        gh=probe_tool("gh", "gh", runner=runner),
    )
