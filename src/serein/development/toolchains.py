"""Shared version-probing helper used by every language module.

Centralizing this one pattern (run ``<binary> --version``, extract the
first version-looking token, degrade to "not installed" on any failure)
avoids scattering near-identical ``try/except`` blocks across
``git.py``/``python.py``/``node.py``/etc. — see docs/development/
architecture.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from serein.development.models import ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner

_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?(?:[-+.\w]*)?")


def _extract_version(text: str) -> str | None:
    match = _VERSION_RE.search(text)
    return match.group(0) if match else None


def probe_tool(
    tool_id: str,
    binary: str,
    version_args: Sequence[str] = ("--version",),
    runner: CommandRunner = DEFAULT_RUNNER,
) -> ToolStatus:
    """Runs ``binary version_args`` and reports install/version state.
    Never raises: a missing binary, a timeout, or unparsable output are
    all just "not installed" / "version unknown", not an error."""
    result = runner.run([binary, *version_args])
    if result is None:
        return ToolStatus(id=tool_id, installed=False, version=None)
    # Some tools (older git-lfs, some `--version` implementations) exit
    # non-zero yet still print a usable version string to stdout/stderr;
    # treat "we got any output at all" as installed, since the binary
    # clearly exists and ran.
    text = f"{result.stdout}\n{result.stderr}"
    if not text.strip():
        return ToolStatus(id=tool_id, installed=False, version=None)
    return ToolStatus(id=tool_id, installed=True, version=_extract_version(text))
