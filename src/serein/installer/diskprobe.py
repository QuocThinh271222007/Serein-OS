"""Read-only disk inventory probing (S7.1 Section 10).

Every value comes from real tool output (``lsblk -J -O -b``, plus a
best-effort ``/dev/disk/by-path`` scan for ``id_path``) via the same
injectable ``CommandRunner`` idiom every other Serein subsystem already
uses (``serein.development.runner``) - never raw ``subprocess`` calls,
never a value fabricated when evidence is absent (``None``/empty stays
``None``/empty). This module never mounts, formats, or writes anything
- it only ever reads.

Windows/install-media/mount-state classification here is intentionally
best-effort (Section 13) - it is never the safety boundary itself. The
safety boundary is ``serein.installer.diskguard``: every disk starts
``protected=True`` regardless of what this module could or could not
determine about it.
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.installer.models import DiskInfo, DiskInventory, PartitionInfo

DEFAULT_ROOT = Path("/")

#: Partition/disk label substrings (case-insensitive) that are
#: best-effort evidence of a Windows-managed volume (Section 13) -
#: never authoritative; an unknown/unlabeled disk remains protected
#: regardless.
_WINDOWS_EFI_LABEL_MARKERS = ("system", "efi")
_WINDOWS_RECOVERY_LABEL_MARKERS = ("recovery", "winre")
_WINDOWS_DATA_FSTYPES = ("ntfs",)

#: Filesystem types that indicate optical/install media rather than a
#: normal writable disk.
_INSTALL_MEDIA_FSTYPES = ("iso9660", "udf")


def _as_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value in ("1", "true", "True"):
            return True
        if value in ("0", "false", "False", ""):
            return False
    return None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _device_path(name: object, path: object) -> str:
    if isinstance(path, str) and path:
        return path
    return f"/dev/{name}"


def _partition_from_node(node: dict) -> PartitionInfo:
    mountpoint = _as_str(node.get("mountpoint"))
    if mountpoint is None:
        mountpoints = node.get("mountpoints")
        if isinstance(mountpoints, list) and mountpoints:
            mountpoint = _as_str(mountpoints[0])
    return PartitionInfo(
        device_path=_device_path(node.get("name"), node.get("path")),
        kernel_name=_as_str(node.get("kname")),
        size_bytes=_as_int(node.get("size")),
        filesystem=_as_str(node.get("fstype")),
        label=_as_str(node.get("label")),
        partition_uuid=_as_str(node.get("partuuid") or node.get("uuid")),
        mounted=mountpoint is not None,
        mountpoint=mountpoint,
    )


def _classify_windows(disk_fstype: str | None, partitions: tuple[PartitionInfo, ...]) -> (
    tuple[bool, bool, bool]
):
    """Best-effort Windows classification (Section 13) - returns
    ``(windows_detected, windows_efi_detected, windows_recovery_detected)``.
    Never authoritative: a disk this returns ``(False, False, False)``
    for is still fully protected unless it is the explicitly selected
    target."""
    windows_efi = False
    windows_recovery = False
    windows_data = False

    fstypes = [disk_fstype, *(p.filesystem for p in partitions)]

    for partition in partitions:
        if not partition.label:
            continue
        lowered = partition.label.lower()
        if partition.filesystem and partition.filesystem.lower() == "vfat" and any(
            marker in lowered for marker in _WINDOWS_EFI_LABEL_MARKERS
        ):
            windows_efi = True
        if any(marker in lowered for marker in _WINDOWS_RECOVERY_LABEL_MARKERS):
            windows_recovery = True

    for fstype in fstypes:
        if fstype and fstype.lower() in _WINDOWS_DATA_FSTYPES:
            windows_data = True

    windows_detected = windows_efi or windows_recovery or windows_data
    return windows_detected, windows_efi, windows_recovery


def _probe_id_path(kernel_name: str, root: Path) -> str | None:
    """Best-effort ``ID_PATH`` via a ``/dev/disk/by-path`` symlink scan
    - real evidence only, never guessed. Returns ``None`` (not an
    error) if the directory does not exist or no symlink resolves to
    this device (e.g. non-Linux host, or a fixture tree in tests)."""
    by_path_dir = root / "dev" / "disk" / "by-path"
    if not by_path_dir.is_dir():
        return None
    try:
        entries = sorted(by_path_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            target = entry.resolve()
        except OSError:
            continue
        if target.name == kernel_name:
            return entry.name
    return None


def _disk_from_node(node: dict, root: Path) -> DiskInfo:
    kernel_name = str(node.get("kname") or node.get("name") or "")
    device_path = _device_path(node.get("name"), node.get("path"))

    partitions = tuple(
        _partition_from_node(child)
        for child in node.get("children", []) or []
        if child.get("type") == "part"
    )

    disk_fstype = _as_str(node.get("fstype"))
    filesystem_signatures = tuple(
        sorted({fs for fs in (disk_fstype, *(p.filesystem for p in partitions)) if fs})
    )

    disk_mountpoint = _as_str(node.get("mountpoint"))
    mounted = disk_mountpoint is not None or any(p.mounted for p in partitions)

    install_media = bool(disk_fstype and disk_fstype.lower() in _INSTALL_MEDIA_FSTYPES) or bool(
        node.get("ro") and disk_fstype and disk_fstype.lower() in _INSTALL_MEDIA_FSTYPES
    )

    windows_detected, windows_efi, windows_recovery = _classify_windows(disk_fstype, partitions)

    serial = _as_str(node.get("serial"))
    wwn = _as_str(node.get("wwn"))
    id_path = _probe_id_path(kernel_name, root) if kernel_name else None

    known = sum(1 for v in (serial, wwn, id_path) if v)
    if serial and wwn:
        confidence = "high"
    elif known >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    return DiskInfo(
        device_path=device_path,
        canonical_path=device_path,
        kernel_name=kernel_name or None,
        model=_as_str(node.get("model")),
        vendor=_as_str(node.get("vendor")),
        serial=serial,
        wwn=wwn,
        id_path=id_path,
        size_bytes=_as_int(node.get("size")),
        logical_sector_size=_as_int(node.get("log-sec")),
        physical_sector_size=_as_int(node.get("phy-sec")),
        transport=_as_str(node.get("tran")),
        removable=_as_bool(node.get("rm")),
        partition_table=_as_str(node.get("pttype")),
        partitions=partitions,
        filesystem_signatures=filesystem_signatures,
        install_media=install_media,
        mounted=mounted,
        windows_detected=windows_detected,
        windows_efi_detected=windows_efi,
        windows_recovery_detected=windows_recovery,
        # protected/target_eligible are deliberately left at their
        # fail-closed dataclass defaults (True/False) here -
        # serein.installer.diskguard.classify_protection is the one
        # place that may ever change them, and only relative to an
        # explicitly selected target.
        identity_confidence=confidence,
    )


def probe_disks(
    runner: CommandRunner = DEFAULT_RUNNER, root: Path = DEFAULT_ROOT
) -> DiskInventory:
    """Build a :class:`DiskInventory` from real ``lsblk`` output.

    Fail-soft, never raises: if ``lsblk`` is unavailable, is not JSON,
    or the command fails, returns an empty inventory - callers (the
    safety gate, the CLI) must treat "no disks observed" as "nothing is
    eligible", never as license to proceed."""
    result = runner.run(["lsblk", "--json", "--output-all", "--bytes", "--paths"])
    if result is None or result.returncode != 0:
        return DiskInventory(disks=())

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return DiskInventory(disks=())

    devices = data.get("blockdevices", [])
    if not isinstance(devices, list):
        return DiskInventory(disks=())

    disks = tuple(
        _disk_from_node(node, root)
        for node in devices
        if isinstance(node, dict) and node.get("type") == "disk"
    )
    return DiskInventory(disks=disks)
