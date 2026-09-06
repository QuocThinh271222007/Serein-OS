"""Shared helpers: safe home-directory resolution for marker checks
(``~/.nvm``, ``~/.pyenv``, etc.) — never printed or returned to a caller,
only used to decide a boolean. Mirrors ``hardware._util``'s
injectable-root pattern for the same testability reasons."""

from __future__ import annotations

from pathlib import Path


def default_home() -> Path:
    try:
        return Path.home()
    except RuntimeError:
        return Path("/nonexistent-serein-default-home")


def marker_exists(home: Path, *relative_parts: str) -> bool:
    try:
        return home.joinpath(*relative_parts).exists()
    except OSError:
        return False
