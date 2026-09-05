"""Kernel identification via ``/proc/sys/kernel/*``, with a ``platform``
module fallback when probing the real host on a non-Linux system (e.g. a
developer's machine) so the CLI never crashes for lack of ``/proc``.
"""

from __future__ import annotations

import platform
from pathlib import Path

from serein.hardware._util import is_real_root, read_text
from serein.hardware.models import KernelInfo


def read_kernel_info(root: Path) -> KernelInfo:
    ostype = read_text(root / "proc" / "sys" / "kernel" / "ostype")
    osrelease = read_text(root / "proc" / "sys" / "kernel" / "osrelease")
    version = read_text(root / "proc" / "sys" / "kernel" / "version")

    if ostype is None and osrelease is None and version is None:
        if is_real_root(root):
            return KernelInfo(
                name=platform.system() or None,
                release=platform.release() or None,
                version=platform.version() or None,
            )
        return KernelInfo()

    return KernelInfo(
        name=ostype.strip() if ostype else None,
        release=osrelease.strip() if osrelease else None,
        version=version.strip() if version else None,
    )
