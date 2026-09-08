"""QEMU boot-smoke harness (S7.0 Sections 44-49, 92, 94-95; marker-aware
live monitoring and UEFI evidence fidelity added by S7.0RM Corrective D/F;
canonical systemd target-marker recognition added by S7.0RM7).

Validates that built media actually boots - never "the QEMU process
stayed alive for N seconds" (Section 46), always a positive marker read
back from a serial console log. Pure boot validation only: no disk is
ever attached (Section 44/92 - "no target disk needed unless the boot
environment requires one", and pure boot smoke never does), no physical
host disk is ever passed through, and the run always has a finite
timeout that produces a captured diagnostic log on failure (Section 48).

**A running QEMU process is not a failure** (S7.0RM Corrective D): a
successfully booted live Ubuntu session is *expected* to keep running,
not exit on its own. The original S7.0R harness used a single blocking
``subprocess.run(..., timeout=...)`` call, which meant a real, correct
boot would always be reported as "timed out" - logically backwards for
a live OS. ``run_boot_smoke`` now polls the growing serial log while
QEMU keeps running, reports success the moment a positive marker
appears, and only then deliberately terminates the process - a genuine
process-exit-before-marker or a deadline with no marker are the only
failure paths.

A QA-only serial boot entry (``console=ttyS0``) is what makes a
positive marker observable at all; it is kept structurally separate from
the normal graphical boot entry (Section 47) - see
``distribution/boot/qa-serial-entry.cfg`` and
``serein.distribution.qa_boot`` for the real, build-time derivation.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

#: Legacy/historical systemd log lines kept for backward compatibility
#: (Section 5 of S7.0RM7) - matched as a plain substring, exactly as
#: before. Real Layer-B Run #8's serial log proved MODERN systemd
#: instead emits ``Reached target basic.target - Basic System.`` (with
#: the real unit name and a trailing period, sometimes ANSI-wrapped),
#: which none of these literal strings match - see
#: `_TARGET_MARKER_PATTERNS` below for the fix. Ordered from the least
#: to most demanding milestone; callers may pass a narrower tuple if
#: they specifically need graphical-target evidence.
DEFAULT_SUCCESS_MARKERS: tuple[str, ...] = (
    "Reached target Basic System",
    "Reached target Multi-User System",
    "Reached target Graphical Interface",
)

#: Strip ANSI CSI/SGR terminal control sequences (e.g. the color codes
#: real serial output wraps around ``[  OK  ]`` and target names) -
#: exactly the well-defined CSI escape shape (ESC ``[``, parameter/
#: intermediate bytes, one final byte), never a broader/destructive
#: filter that could rewrite unrelated semantic text (S7.0RM7
#: Corrective A/Section 3).
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

#: Canonical, modern systemd "reached target" success lines (S7.0RM7
#: Corrective B) - a real Layer-B run's serial log contained
#: ``Reached target basic.target - Basic System.`` verbatim, which the
#: legacy literal marker set above never recognized, even though the
#: real OS had genuinely reached that milestone. Each pattern requires
#: an explicit reached-target EVENT for a real target unit - never
#: merely the target's name appearing in an unrelated line. Evaluated
#: against text with ANSI escapes already stripped (`_strip_ansi`).
#: Deliberately does NOT match, e.g.:
#:   "Queued start job for default target basic.target"
#:   "Starting basic.target"
#:   "Wants=basic.target" / "After=basic.target"
#:   "Started arbitrary.service"
_TARGET_MARKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Reached target\s+basic\.target\s*-\s*Basic System\.?", re.IGNORECASE),
    re.compile(
        r"Reached target\s+multi-user\.target\s*-\s*Multi-User System\.?", re.IGNORECASE
    ),
    re.compile(
        r"Reached target\s+graphical\.target\s*-\s*Graphical Interface\.?", re.IGNORECASE
    ),
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI CSI/SGR terminal control sequences from ``text`` -
    evaluation-only normalization (S7.0RM7 Corrective A/Section 3).
    The raw captured serial log on disk is never modified; only the
    in-memory text handed to the marker parser is normalized."""
    return _ANSI_ESCAPE_RE.sub("", text)

DEFAULT_TIMEOUT_SECONDS = 300

#: TCG (software emulation - no hardware virtualization, e.g. a stock
#: GitHub-hosted runner with no ``/dev/kvm``) genuinely needs more
#: wall-clock time than KVM to reach the same real userspace milestone
#: (S7.0RM6 Corrective D/Section 11). A real Layer-B run's serial log
#: proved the boot had genuinely progressed into real systemd/apparmor/
#: snapd userspace activity - it simply had not yet matched a closure
#: marker within the prior fixed 300s bound. Still finite either way -
#: never unbounded, and a longer bound alone can never itself cause a
#: PASS (only a real positive marker can).
DEFAULT_TIMEOUT_SECONDS_TCG = 600

DEFAULT_MEMORY_MB = 2048
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_TERMINATE_GRACE_SECONDS = 10.0


def default_timeout_seconds_for_accel(accel: str) -> int:
    """The one place an accelerator-specific default timeout is
    decided (mirrors :func:`derive_boot_mode`'s "one place" discipline)
    - ``"tcg"`` gets the longer, still-bounded allowance; every other
    value (in practice only ``"kvm"``) keeps the original
    :data:`DEFAULT_TIMEOUT_SECONDS`. A caller-supplied explicit
    ``--timeout``/``timeout_seconds`` always overrides this."""
    return DEFAULT_TIMEOUT_SECONDS_TCG if accel == "tcg" else DEFAULT_TIMEOUT_SECONDS

#: Bounded tail read per poll (Section 26 - "do not repeatedly read
#: unbounded multi-MB logs") - generous enough to always contain a
#: marker near the growing end of the file.
_LOG_TAIL_BYTES = 65_536


class BootSmokeError(RuntimeError):
    """Raised for a harness-construction error (never for a boot
    failure itself - that is reported in :class:`BootSmokeResult`, not
    raised, so a real failed boot is captured evidence, not a crash)."""


def derive_boot_mode(ovmf_code: Path | None) -> str:
    """The one place ``boot_mode`` is decided (Section 37 of S7.0RM) -
    never a caller-supplied string that could disagree with what the
    QEMU command actually does. ``ovmf_code`` present means a UEFI
    pflash drive was actually added to the command; its absence means
    legacy BIOS. Evidence must always read this back, never assume."""
    return "uefi" if ovmf_code is not None else "bios"


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
    omitting it boots via legacy BIOS (Section 95) - see
    :func:`derive_boot_mode` for how evidence reflects this decision.
    """
    if not iso_path.name:
        raise BootSmokeError("iso_path must name a real ISO file")

    # No kernel -append flags here by design: the QA serial boot entry
    # lives inside the ISO's own GRUB config, derived and installed as
    # the auto-selected default by serein.distribution.qa_boot - not
    # injected from the QEMU command line, keeping the normal graphical
    # entry and the QA entry structurally separate (Section 47) even at
    # the harness layer.
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
    log_text: str,
    markers: tuple[str, ...] = DEFAULT_SUCCESS_MARKERS,
    target_patterns: tuple[re.Pattern[str], ...] = _TARGET_MARKER_PATTERNS,
) -> tuple[bool, str | None]:
    """Return ``(success, matched_marker)``. ``success`` is only ever
    ``True`` because a real, explicit reached-target/reached-system
    event was found in the captured serial log - never inferred from
    process exit status alone, and never from mere service/subsystem
    activity (``snapd``, ``apparmor``, ``cloud-init``, ``Started
    ...service``, etc.).

    Two independent, both-strict recognition layers (S7.0RM7):

    - ``markers`` - legacy literal substrings, kept for backward
      compatibility with the historical marker text.
    - ``target_patterns`` - canonical modern systemd
      ``Reached target <unit> - <Description>`` lines (real Layer-B
      Run #8 evidence), matched after stripping ANSI terminal control
      sequences a real serial console can interleave around them
      (``_strip_ansi``) - never by loosening what counts as a match.

    ``matched_marker`` is always the real evidence that caused success:
    either the literal legacy string, or the exact (whitespace-
    normalized) matched systemd line - never a bare unit name like
    ``"basic.target"`` alone.
    """
    for marker in markers:
        if marker in log_text:
            return True, marker

    normalized = _strip_ansi(log_text)
    for pattern in target_patterns:
        match = pattern.search(normalized)
        if match:
            matched_text = " ".join(match.group(0).split())
            return True, matched_text

    return False, None


@dataclass(frozen=True)
class BootSmokeResult:
    status: str  # "pass" | "fail" | "not_performed"
    matched_marker: str | None
    reason: str
    log_excerpt: str
    boot_mode: str = "bios"
    firmware: str | None = None
    # S7.0RM6 Corrective B/Section 10: narrow, bounded diagnostic
    # fields for closure investigation (e.g. deciding whether a real
    # timeout needs a longer bound or reveals a genuine blocker) -
    # deliberately never the full serial log itself, which stays a
    # separate uploaded artifact (log_excerpt above is already bounded
    # to the last 4000 chars).
    timeout_seconds: int = 0
    accelerator: str = "tcg"
    serial_log_path: str | None = None
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        # Required invariant (Section 29): status == pass implies a
        # real, non-empty matched marker - never a pass with no
        # evidence behind it.
        if self.status == "pass" and not self.matched_marker:
            raise BootSmokeError("BootSmokeResult status=pass requires a non-empty matched_marker")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "boot_mode": self.boot_mode,
            "firmware": self.firmware,
            "matched_marker": self.matched_marker,
            "target_disk_count": 0,
            "timeout_seconds": self.timeout_seconds,
            "accelerator": self.accelerator,
            "serial_log_path": self.serial_log_path,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


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
    """Terminate, wait a bounded grace period, kill if still alive -
    the one exit path every run_boot_smoke branch uses, so QEMU is
    never leaked on CI (Section 25)."""
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


def run_boot_smoke(
    iso_path: Path,
    work_dir: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    terminate_grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
    accel: str = "tcg",
    ovmf_code: Path | None = None,
    markers: tuple[str, ...] = DEFAULT_SUCCESS_MARKERS,
    popen_factory: object = subprocess.Popen,
    time_source: object = time.monotonic,
    sleep_fn: object = time.sleep,
) -> BootSmokeResult:
    """Launch QEMU and poll the growing serial log while it keeps
    running, reporting success the moment a positive marker appears -
    never inferring anything from the process merely staying alive
    (Section 46) or merely exiting (a live boot is expected to keep
    running, not exit - Section 22-23).

    ``popen_factory`` is injectable (must behave like
    ``subprocess.Popen``: ``.poll()``, ``.terminate()``, ``.kill()``,
    ``.wait(timeout=...)``) so this whole state machine is unit-testable
    with a fake process and a fake clock, never a real multi-minute
    wait (Section 55).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    serial_log_path = work_dir / "boot-smoke-serial.log"
    if serial_log_path.exists():
        serial_log_path.unlink()

    boot_mode = derive_boot_mode(ovmf_code)
    command = build_qemu_boot_command(
        iso_path, serial_log_path, accel=accel, ovmf_code=ovmf_code
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
                        f"qemu exited (code {returncode}) before any positive "
                        "boot marker was observed"
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
                    reason=f"boot smoke timed out after {timeout_seconds}s with no success marker",
                    log_excerpt=log_text[-4000:], boot_mode=boot_mode,
                    firmware=str(ovmf_code) if ovmf_code else None,
                    timeout_seconds=timeout_seconds, accelerator=accel,
                    serial_log_path=str(serial_log_path), elapsed_seconds=_elapsed(),
                )

            sleep_fn(poll_interval_seconds)  # type: ignore[operator]
    finally:
        _terminate(process, terminate_grace_seconds)
