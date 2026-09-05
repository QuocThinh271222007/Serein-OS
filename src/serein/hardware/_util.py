"""Shared helpers for safe, non-raising filesystem probing."""

from __future__ import annotations

from pathlib import Path

#: Stand-in for the real filesystem root. Passed explicitly through every
#: probe function so tests can substitute a fixture directory tree.
DEFAULT_ROOT = Path("/")


def read_text(path: Path) -> str | None:
    """Read a file as text, returning None on any failure.

    Hardware/OS interfaces are inherently unreliable: files may be absent,
    permission-denied, or briefly disappear (as with some sysfs nodes).
    None of that is exceptional for a read-only prober.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_int(path: Path) -> int | None:
    text = read_text(path)
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def is_real_root(root: Path) -> bool:
    """True when ``root`` is the actual filesystem root rather than a
    fixture directory standing in for it.

    Used to gate fallbacks (e.g. the ``platform`` module) that must never
    leak real host data into a fixture-driven test.
    """
    return root == DEFAULT_ROOT
