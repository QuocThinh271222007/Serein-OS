"""``serein installer status`` - read-only summary (S7.1 Section 23-24).

Never probes destructively, never triggers installation - only ever
reports what :func:`serein.installer.diskprobe.probe_disks` and a
``curtin --version`` check observe right now."""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.installer.diskprobe import DEFAULT_ROOT, probe_disks
from serein.installer.models import InstallerStatus


def build_installer_status(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> InstallerStatus:
    curtin_result = runner.run(["curtin", "--version"])
    installer_backend_available = curtin_result is not None and curtin_result.returncode == 0

    lsblk_result = runner.run(["lsblk", "--version"])
    disk_probe_tool_available = lsblk_result is not None and lsblk_result.returncode == 0

    inventory = probe_disks(runner=runner, root=root)

    return InstallerStatus(
        installer_backend="curtin" if installer_backend_available else None,
        installer_backend_available=installer_backend_available,
        disk_probe_tool_available=disk_probe_tool_available,
        disk_count_observed=len(inventory.disks),
    )
