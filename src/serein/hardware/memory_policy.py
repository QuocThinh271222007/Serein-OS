"""Swap and ZRAM detection.

Never modifies swap or ZRAM state — read-only, mirroring every other S2
detector. ``/proc/swaps`` lists every active swap backend (disk-backed or
ZRAM) uniformly; a device is classified as ``"zram"`` by name rather than
by trusting its reported ``Type`` column, since the kernel reports ZRAM
swap as a plain ``partition`` like any other block-device swap. See
``docs/hardware/memory-policy.md`` for the sizing policy this feeds.

S2R correction: config-source detection now scans every real
``systemd-zram-generator`` search path and requires an actual ``[zramN]``
section header before treating a file as configuration — an empty
``zram-generator.conf.d/`` directory (or one containing only unrelated
files) is no longer a false positive for "already configured". Search
paths and precedence are exactly as documented in the real, installed
``zram-generator.conf(5)`` (verified against systemd-zram-generator
1.2.1-2 on Ubuntu 26.04 — see ``docs/validation/s2r/zram-validation.md``).

S2R micro-corrective: ``detect_zram_capability`` is the single source of
truth for "can Serein manage ZRAM here" — both ``capabilities.py`` and
``planner.py`` call this one function instead of each independently
deciding, closing a real gap where the planner could propose ``APPLY``
for a machine the capability model had already said couldn't support it.
"""

from __future__ import annotations

import re
from pathlib import Path

from serein.hardware._util import read_int, read_text
from serein.hardware.models import (
    EnvironmentInfo,
    MemoryPolicyInfo,
    SwapDevice,
    ZramCapability,
    ZramDevice,
)

_ZRAM_CAPABILITY_MECHANISM = (
    "sysfs:/sys/class/zram-control (kernel), systemd-zram-generator (config mechanism)"
)

# Real search paths and precedence order, per the installed
# zram-generator.conf(5) SYNOPSIS: the base conf file is read first (and
# has the LOWEST precedence); *.conf snippets under each conf.d directory
# are then merged, sorted lexicographically by filename across all four
# directories combined. Serein does not need to resolve final precedence
# for S2R — only to avoid missing a real source or double-counting.
_SEARCH_BASE_DIRS = (
    "usr/lib/systemd",
    "usr/local/lib/systemd",
    "etc/systemd",
    "run/systemd",
)

_ZRAM_SECTION_RE = re.compile(r"(?m)^\s*\[zram\d+\]")


def _parse_swaps(text: str) -> list[SwapDevice]:
    lines = text.splitlines()
    devices: list[SwapDevice] = []
    for line in lines[1:]:  # first line is the column header
        parts = line.split()
        if len(parts) < 5:
            continue
        filename, swap_type, size_kib, _used_kib, priority = parts[:5]
        kind = "zram" if "zram" in filename else swap_type
        try:
            size_bytes: int | None = int(size_kib) * 1024
        except ValueError:
            size_bytes = None
        try:
            prio: int | None = int(priority)
        except ValueError:
            prio = None
        devices.append(SwapDevice(name=filename, kind=kind, size_bytes=size_bytes, priority=prio))
    return devices


def _active_algorithm(comp_algorithm_text: str) -> str | None:
    for token in comp_algorithm_text.split():
        if token.startswith("[") and token.endswith("]"):
            return token[1:-1]
    return None


def _detect_zram_devices(root: Path) -> list[ZramDevice]:
    block_dir = root / "sys" / "block"
    if not block_dir.is_dir():
        return []
    try:
        names = sorted(p.name for p in block_dir.iterdir() if p.name.startswith("zram"))
    except OSError:
        return []

    devices: list[ZramDevice] = []
    for name in names:
        disksize = read_int(block_dir / name / "disksize")
        algo_text = read_text(block_dir / name / "comp_algorithm")
        devices.append(
            ZramDevice(
                name=name,
                disksize_bytes=disksize,
                comp_algorithm=_active_algorithm(algo_text) if algo_text else None,
            )
        )
    return devices


def _has_zram_section(text: str) -> bool:
    """A file existing is not configuration — it must actually declare a
    ``[zramN]`` section. An empty file, a fully-commented-out file, or an
    empty ``conf.d`` directory are all "no configuration", not "ambiguous
    configuration" or "configured"."""
    return bool(_ZRAM_SECTION_RE.search(text))


def _scan_zram_generator_config(root: Path) -> list[str]:
    """Every real, meaningful config source found, as display paths
    (e.g. ``/etc/systemd/zram-generator.conf.d/90-serein.conf``) — not a
    single boolean. Empty list means genuinely unconfigured."""
    sources: list[str] = []

    for base in _SEARCH_BASE_DIRS:
        base_conf = root / base / "zram-generator.conf"
        text = read_text(base_conf)
        if text and _has_zram_section(text):
            sources.append(f"/{base}/zram-generator.conf")

        confd_dir = root / base / "zram-generator.conf.d"
        if not confd_dir.is_dir():
            continue
        try:
            conf_files = sorted(p for p in confd_dir.iterdir() if p.name.endswith(".conf"))
        except OSError:
            continue
        for conf_file in conf_files:
            snippet_text = read_text(conf_file)
            if snippet_text and _has_zram_section(snippet_text):
                sources.append(f"/{base}/zram-generator.conf.d/{conf_file.name}")

    return sources


def detect_memory_policy(root: Path) -> MemoryPolicyInfo:
    swaps_text = read_text(root / "proc" / "swaps")
    swap_devices = _parse_swaps(swaps_text) if swaps_text else []
    config_sources = _scan_zram_generator_config(root)

    return MemoryPolicyInfo(
        swap_devices=swap_devices,
        zram_devices=_detect_zram_devices(root),
        zram_generator_config_sources=config_sources,
        zram_generator_config_ambiguous=len(config_sources) > 1,
    )


def _zram_kernel_support(root: Path, existing_zram_devices: list[ZramDevice]) -> bool:
    """Real, checkable evidence that the kernel can create zram devices
    on demand - not an assumption. ``/sys/class/zram-control`` is the
    kernel's own hot-add/hot-remove control interface (present once the
    zram module is loaded or built in); a "zram" line in /proc/modules,
    or an already-existing /sys/block/zram* device, are equally valid
    independent signals."""
    if (root / "sys" / "class" / "zram-control").is_dir():
        return True
    if existing_zram_devices:
        return True
    modules_text = read_text(root / "proc" / "modules")
    if modules_text:
        for line in modules_text.splitlines():
            fields = line.split()
            if fields and fields[0] == "zram":
                return True
    return False


def detect_zram_capability(
    root: Path, environment: EnvironmentInfo, memory_policy: MemoryPolicyInfo
) -> ZramCapability:
    """The single source of truth for "can Serein manage ZRAM here" —
    call this from both ``capabilities.py`` and ``planner.py`` rather
    than deriving the answer independently in each. Never returns
    ``available=True`` under WSL/a container: verified live
    (docs/validation/s2r/zram-validation.md) that systemd-zram-generator's
    own generator declines to run there."""
    if environment.virtualization == "wsl" or environment.is_container:
        label = "WSL" if environment.virtualization == "wsl" else "container"
        return ZramCapability(
            available=False,
            confidence="high",
            mechanism="systemd-zram-generator",
            reason=(
                f"Running under {label}: systemd-zram-generator's own generator "
                "declines to create devices when systemd-detect-virt reports a "
                "container context (verified behavior, includes WSL2)."
            ),
        )

    if _zram_kernel_support(root, memory_policy.zram_devices):
        return ZramCapability(
            available=True,
            confidence="high",
            mechanism=_ZRAM_CAPABILITY_MECHANISM,
            reason=(
                "The kernel's zram-control hot-add interface (or an existing zram "
                "device/module) confirms zram support is present."
            ),
        )

    return ZramCapability(
        available=False,
        confidence="medium",
        mechanism=_ZRAM_CAPABILITY_MECHANISM,
        reason=(
            "No zram-control interface, loaded zram module, or existing zram "
            "device was found; kernel support could not be confirmed."
        ),
    )
