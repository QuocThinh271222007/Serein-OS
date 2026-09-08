"""Installed-target-disk boot validation (S7.1 Sections 29, 47, 51).

Reuses the PROVEN S7.0 marker-aware evaluation primitives
(``serein.distribution.bootsmoke.evaluate_boot_log``/
``DEFAULT_SUCCESS_MARKERS``/``derive_boot_mode``/
``default_timeout_seconds_for_accel``/``BootSmokeResult``) rather than
reimplementing marker recognition (Section 51: "S7.1 builds on that
foundation"). Never reopens S7.0's own QEMU harness internals though -
``run_boot_smoke`` boots a CD-ROM (the install medium); this module
boots a hard-disk image (the INSTALLED target), which is a materially
different QEMU command (no ``-cdrom``, a real ``-drive`` as the boot
device) - S7.1 owns this narrow, new piece rather than bending S7.0's
existing, already-closed function to do two different things.

Same invariants as S7.0's harness: no target disk implicitly written
(the disk is attached ``if=virtio``, boot-only, exactly what the real
installed system needs to run - never a second, separate write target),
a live boot is expected to keep running (never "the process stayed
alive" as evidence), and a finite, bounded timeout on every path.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from serein.distribution.bootsmoke import (
    DEFAULT_MEMORY_MB,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SUCCESS_MARKERS,
    DEFAULT_TERMINATE_GRACE_SECONDS,
    BootSmokeError,
    BootSmokeResult,
    default_timeout_seconds_for_accel,
    derive_boot_mode,
    evaluate_boot_log,
)

__all__ = [
    "build_installed_disk_boot_command",
    "run_installed_disk_boot_check",
    "default_timeout_seconds_for_accel",
]

_LOG_TAIL_BYTES = 65_536


def build_installed_disk_boot_command(
    target_disk_path: Path,
    serial_log_path: Path,
    memory_mb: int = DEFAULT_MEMORY_MB,
    accel: str = "tcg",
    ovmf_code: Path | None = None,
    extra_disk_paths: tuple[Path, ...] = (),
) -> list[str]:
    """QEMU argv to boot the INSTALLED target disk itself (Section 47) -
    no install medium attached at all (``INSTALL_MEDIA_ATTACHED=false``),
    the target disk is always the FIRST (and therefore boot) device.
    Never a ``-cdrom`` here - that would defeat the entire point of this
    check (proving the target is bootable on its own, self-contained
    ESP+root).

    ``extra_disk_paths`` optionally attaches additional disks (e.g. the
    protected-disk fixture) so Section 15's acceptance scenario
    ("protected disk present + Serein target present -> Serein boots")
    can be exercised in the SAME run as the stronger, protected-disk-
    absent self-containment proof (Section 47) - never the boot
    device itself, and never written to by a boot-only path."""
    if not target_disk_path.name:
        raise BootSmokeError("target_disk_path must name a real disk image")

    command = [
        "qemu-system-x86_64",
        "-m", str(memory_mb),
        "-accel", accel,
        "-drive", f"if=virtio,format=qcow2,file={target_disk_path}",
    ]
    for extra_disk_path in extra_disk_paths:
        command += ["-drive", f"if=virtio,format=qcow2,file={extra_disk_path}"]
    command += [
        "-boot", "c",
        "-display", "none",
        "-no-reboot",
        "-serial", f"file:{serial_log_path}",
    ]
    if ovmf_code is not None:
        command += ["-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}"]
    return command


def _read_tail(path: Path, max_bytes: int = _LOG_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
        data = fh.read()
    return data.decode("utf-8", errors="replace")


def _terminate(process: object, grace_seconds: float) -> None:
    if process.poll() is not None:  # type: ignore[attr-defined]
        return
    process.terminate()  # type: ignore[attr-defined]
    try:
        process.wait(timeout=grace_seconds)  # type: ignore[attr-defined]
    except subprocess.TimeoutExpired:
        process.kill()  # type: ignore[attr-defined]
        try:
            process.wait(timeout=grace_seconds)  # type: ignore[attr-defined]
        except subprocess.TimeoutExpired:
            pass


def run_installed_disk_boot_check(
    target_disk_path: Path,
    work_dir: Path,
    timeout_seconds: int,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    terminate_grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
    accel: str = "tcg",
    ovmf_code: Path | None = None,
    extra_disk_paths: tuple[Path, ...] = (),
    markers: tuple[str, ...] = DEFAULT_SUCCESS_MARKERS,
    popen_factory: object = subprocess.Popen,
    time_source: object = time.monotonic,
    sleep_fn: object = time.sleep,
) -> BootSmokeResult:
    """Boot ``target_disk_path`` on its own (no install medium attached)
    and poll for a genuine reached-target marker (Section 29, 47) -
    identical polling discipline to
    ``serein.distribution.bootsmoke.run_boot_smoke``: a running process
    is not evidence, a process exiting before a marker is a real
    failure, a deadline with no marker is a real failure, and the
    process is always terminated on every exit path. ``popen_factory``/
    ``time_source``/``sleep_fn`` are injectable for the same reason
    S7.0's harness makes them injectable - unit-testable without a real
    multi-minute wait."""
    work_dir.mkdir(parents=True, exist_ok=True)
    serial_log_path = work_dir / "installed-boot-serial.log"
    if serial_log_path.exists():
        serial_log_path.unlink()

    boot_mode = derive_boot_mode(ovmf_code)
    command = build_installed_disk_boot_command(
        target_disk_path, serial_log_path, accel=accel, ovmf_code=ovmf_code,
        extra_disk_paths=extra_disk_paths,
    )

    process = popen_factory(  # type: ignore[operator]
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    start_time = time_source()  # type: ignore[operator]
    deadline = start_time + timeout_seconds  # type: ignore[operator]

    def _elapsed() -> float:
        return time_source() - start_time  # type: ignore[operator]

    try:
        while True:
            log_text = _read_tail(serial_log_path)
            success, marker = evaluate_boot_log(log_text, markers)
            if success:
                _terminate(process, terminate_grace_seconds)
                return BootSmokeResult(
                    status="pass", matched_marker=marker, reason=f"matched marker: {marker!r}",
                    log_excerpt=log_text[-4000:], boot_mode=boot_mode,
                    firmware=str(ovmf_code) if ovmf_code else None,
                    timeout_seconds=timeout_seconds, accelerator=accel,
                    serial_log_path=str(serial_log_path), elapsed_seconds=_elapsed(),
                )

            if process.poll() is not None:  # type: ignore[attr-defined]
                returncode = process.returncode  # type: ignore[attr-defined]
                return BootSmokeResult(
                    status="fail", matched_marker=None,
                    reason=(
                        f"installed target qemu exited (code {returncode}) before any "
                        "positive boot marker was observed"
                    ),
                    log_excerpt=log_text[-4000:], boot_mode=boot_mode,
                    firmware=str(ovmf_code) if ovmf_code else None,
                    timeout_seconds=timeout_seconds, accelerator=accel,
                    serial_log_path=str(serial_log_path), elapsed_seconds=_elapsed(),
                )

            if time_source() >= deadline:  # type: ignore[operator]
                _terminate(process, terminate_grace_seconds)
                return BootSmokeResult(
                    status="fail", matched_marker=None,
                    reason=(
                        f"installed target boot check timed out after {timeout_seconds}s "
                        "with no success marker"
                    ),
                    log_excerpt=log_text[-4000:], boot_mode=boot_mode,
                    firmware=str(ovmf_code) if ovmf_code else None,
                    timeout_seconds=timeout_seconds, accelerator=accel,
                    serial_log_path=str(serial_log_path), elapsed_seconds=_elapsed(),
                )

            sleep_fn(poll_interval_seconds)  # type: ignore[operator]
    finally:
        _terminate(process, terminate_grace_seconds)
