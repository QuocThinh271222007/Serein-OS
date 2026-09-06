"""Injectable, read-only command execution.

Every development detector runs commands through a ``CommandRunner``
instead of calling ``subprocess`` directly, so tests can inject a fake
runner instead of depending on real tools being installed (see
``tests/test_development.py``). Production code uses
``SubprocessCommandRunner`` — bounded by a timeout, never ``shell=True``,
never given a command that could install, update, log in, or otherwise
mutate anything (detection commands are exclusively ``--version``/
``--help``-style read-only invocations; see docs/development/
architecture.md's "command safety" section).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

_DEFAULT_TIMEOUT = 3.0


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], timeout: float = _DEFAULT_TIMEOUT) -> CommandResult | None:
        """Returns None if the command could not be found/run/finished in
        time — never raises. A returned result may still have a non-zero
        ``returncode``; callers decide what that means."""
        ...


class SubprocessCommandRunner:
    def run(self, args: Sequence[str], timeout: float = _DEFAULT_TIMEOUT) -> CommandResult | None:
        try:
            proc = subprocess.run(  # noqa: S603 - args is a fixed list, never shell=True
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


DEFAULT_RUNNER = SubprocessCommandRunner()
