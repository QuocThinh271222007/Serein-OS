"""QEMU boot-smoke harness (S7.0 Sections 44-49, 92, 94-95).

Validates that built media actually boots - never "the QEMU process
stayed alive for N seconds" (Section 46), always a positive marker read
back from a serial console log. Pure boot validation only: no disk is
ever attached (Section 44/92 - "no target disk needed unless the boot
environment requires one", and pure boot smoke never does), no physical
host disk is ever passed through, and the run always has a finite
timeout that produces a captured diagnostic log on failure (Section 48).

A QA-only serial boot entry (``console=ttyS0``) is what makes a
positive marker observable at all; it is kept structurally separate from
the normal graphical boot entry (Section 47) - see
``distribution/boot/qa-serial-entry.cfg``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Systemd/casper log lines that constitute genuine positive boot
#: evidence (Section 46) - kernel + initramfs + early userspace really
#: came up, not merely "the emulator didn't crash". Ordered from the
#: least to most demanding milestone; callers may pass a narrower tuple
#: if they specifically need graphical-target evidence.
DEFAULT_SUCCESS_MARKERS: tuple[str, ...] = (
    "Reached target Basic System",
    "Reached target Multi-User System",
    "Reached target Graphical Interface",
)

DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MEMORY_MB = 2048


class BootSmokeError(RuntimeError):
    """Raised for a harness-construction error (never for a boot
    failure itself - that is reported in :class:`BootSmokeResult`, not
    raised, so a real failed boot is captured evidence, not a crash)."""


def build_qemu_boot_command(
    iso_path: Path,
    serial_log_path: Path,
    memory_mb: int = DEFAULT_MEMORY_MB,
    accel: str = "tcg",
    ovmf_code: Path | None = None,
) -> list[str]:
    """Construct the QEMU argv for a pure boot-smoke run.

    Deliberately omits any ``-drive``/``-hda`` target disk (Section 44) -
    the ISO is attached read-only as the boot medium and nothing else is
    ever writable. ``accel="kvm"`` is used only when the caller has
    already confirmed KVM is available (Section 49 - never required in
    normal CI); ``"tcg"`` is the software-emulation fallback that always
    works. Passing ``ovmf_code`` selects a UEFI boot path (Section 94);
    omitting it boots via legacy BIOS (Section 95).
    """
    if not iso_path.name:
        raise BootSmokeError("iso_path must name a real ISO file")

    # No kernel -append flags here by design: the QA serial boot entry
    # lives inside the ISO's own GRUB config
    # (distribution/boot/qa-serial-entry.cfg), selected via the boot
    # menu default this build sets, not injected from the QEMU command
    # line - keeping the normal graphical entry and the QA entry
    # structurally separate (Section 47) even at the harness layer.
    command = [
        "qemu-system-x86_64",
        "-m", str(memory_mb),
        "-accel", accel,
        "-cdrom", str(iso_path),
        "-boot", "d",
        "-display", "none",
        "-no-reboot",
        "-serial", f"file:{serial_log_path}",
    ]
    if ovmf_code is not None:
        command += ["-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}"]
    return command


def evaluate_boot_log(
    log_text: str, markers: tuple[str, ...] = DEFAULT_SUCCESS_MARKERS
) -> tuple[bool, str | None]:
    """Return ``(success, matched_marker)``. ``success`` is only ever
    ``True`` because a real marker string was found in the captured
    serial log - never inferred from process exit status alone."""
    for marker in markers:
        if marker in log_text:
            return True, marker
    return False, None


@dataclass(frozen=True)
class BootSmokeResult:
    status: str  # "pass" | "fail" | "not_performed"
    matched_marker: str | None
    reason: str
    log_excerpt: str


def run_boot_smoke(
    iso_path: Path,
    work_dir: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    accel: str = "tcg",
    ovmf_code: Path | None = None,
    markers: tuple[str, ...] = DEFAULT_SUCCESS_MARKERS,
    subprocess_runner: object = subprocess.run,
) -> BootSmokeResult:
    """Run one bounded QEMU boot-smoke attempt and evaluate the result.

    Always finite (Section 48): a ``subprocess.TimeoutExpired`` is
    caught and reported as ``status="fail"`` with whatever partial
    serial log was captured, never left to hang.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    serial_log_path = work_dir / "boot-smoke-serial.log"
    command = build_qemu_boot_command(
        iso_path, serial_log_path, accel=accel, ovmf_code=ovmf_code
    )

    try:
        subprocess_runner(  # type: ignore[operator]
            command, capture_output=True, text=True, timeout=timeout_seconds, check=False
        )
    except subprocess.TimeoutExpired:
        excerpt = _read_excerpt(serial_log_path)
        return BootSmokeResult(
            status="fail",
            matched_marker=None,
            reason=f"boot smoke timed out after {timeout_seconds}s with no success marker",
            log_excerpt=excerpt,
        )

    log_text = _read_excerpt(serial_log_path)
    success, marker = evaluate_boot_log(log_text, markers)
    if success:
        return BootSmokeResult(
            status="pass", matched_marker=marker, reason=f"matched marker: {marker!r}",
            log_excerpt=log_text,
        )
    return BootSmokeResult(
        status="fail", matched_marker=None,
        reason="qemu exited before any positive boot marker was observed",
        log_excerpt=log_text,
    )


def _read_excerpt(path: Path, max_chars: int = 4000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]
