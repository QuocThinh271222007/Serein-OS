"""Live-media detection (Section 10 - "Do not rely on only one heuristic
if unsafe").

Every signal here is read-only (file existence / text read) and degrades
honestly to ``False`` when unreadable - absence of evidence for one
signal is never treated as evidence of anything. The combined verdict
requires either one structurally strong signal (kernel cmdline naming a
live/casper boot, or an overlay root filesystem - both essentially only
ever true on a live/install medium) or two independent weaker signals
together (casper configuration *and* a live runtime directory).
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import DEFAULT_ROOT, read_text

from .models import LiveMediaEvidence

_CMDLINE_LIVE_TOKENS = ("boot=casper", "boot=live", "boot=iso")


def detect_live_media(root: Path = DEFAULT_ROOT) -> LiveMediaEvidence:
    casper_conf_present = (root / "etc" / "casper.conf").exists()
    live_run_dir_present = (root / "run" / "live").exists() or (
        root / "run" / "live-media"
    ).exists()
    cdrom_dir_present = (root / "cdrom").exists()

    cmdline_text = read_text(root / "proc" / "cmdline") or ""
    cmdline_indicates_live = any(token in cmdline_text for token in _CMDLINE_LIVE_TOKENS)

    mounts_text = read_text(root / "proc" / "mounts")
    overlay_root_fs = _root_is_overlay(mounts_text)

    reasons: list[str] = []
    if cmdline_indicates_live:
        reasons.append("kernel cmdline indicates a live/casper/iso boot")
    if overlay_root_fs:
        reasons.append("root filesystem ('/') is mounted as an overlay - typical of a live session")
    if casper_conf_present and live_run_dir_present:
        reasons.append("/etc/casper.conf and /run/live are both present")
    if cdrom_dir_present and casper_conf_present:
        reasons.append("/cdrom mountpoint present alongside casper configuration")

    is_live = (
        cmdline_indicates_live
        or overlay_root_fs
        or (casper_conf_present and live_run_dir_present)
    )

    return LiveMediaEvidence(
        is_live_media=is_live,
        reasons=tuple(reasons),
        casper_conf_present=casper_conf_present,
        live_run_dir_present=live_run_dir_present,
        cmdline_indicates_live=cmdline_indicates_live,
        overlay_root_fs=overlay_root_fs,
        cdrom_dir_present=cdrom_dir_present,
    )


def _root_is_overlay(mounts_text: str | None) -> bool:
    if not mounts_text:
        return False
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "/" and parts[2] == "overlay":
            return True
    return False
