"""Atomic JSON state writes (Section 27 - "Provisioning state must not
become corrupt on power loss").

Pattern: write to a temp file in the *same directory* as the target
(so the final ``os.replace`` is a same-filesystem rename, which POSIX
guarantees is atomic), ``fsync`` the temp file's contents (best-effort -
not every filesystem/platform supports it), then ``os.replace`` onto the
real path. The real path is never opened for writing directly, so a
crash mid-write can only ever leave behind an orphaned ``.tmp`` file -
never a truncated/partial real state file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                # Not every filesystem/platform supports fsync (e.g. some
                # network filesystems, or this repository's Windows dev
                # environment for certain paths) - best-effort only, never
                # fatal, since the rename below is the real safety net.
                pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
