"""S7.1R22: storage-probe evidence TRIGGER-reliability regression tests.

Real S7.1R21-TCG-REPRO-1 evidence proved a genuine defect: a real
Filesystem/_probe/probe_once cancellation and a real block_probe_fail
both demonstrably occurred in-guest while the watcher and evidence
channel were both alive, yet storage_probe_frame_count stayed 0 - the
old shared 200-line `recent_journal` snapshot used for storage-TRIGGER
DETECTION let unrelated journal volume scroll the real trigger line
out of the window between one 10s poll and the next.

These tests run the REAL generated watcher script
(serein.installer.renderer.build_qa_evidence_watcher_script) end to
end via `/bin/sh`, against a controlled stub `journalctl` and a fake
crash-file directory - never a mock of the Python renderer itself.
Skipped (not failed) on a host with no POSIX `/bin/sh` or no
`journalctl` on PATH (Windows CI, sandboxes without systemd tooling),
since this behavior is guest-OS shell behavior, not Python behavior.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from serein.installer.renderer import build_qa_evidence_watcher_script

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None,
    reason="the generated watcher is a POSIX /bin/sh script - only runnable on a "
    "POSIX host",
)

_REAL_JOURNALCTL = shutil.which("journalctl")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_watcher(tmp_path: Path) -> Path:
    script_path = tmp_path / "watcher.sh"
    script_path.write_text(build_qa_evidence_watcher_script())
    return script_path


def _run_watcher(
    tmp_path: Path,
    stub_journalctl: str,
    *,
    iterations: int = 2,
    crash_files: dict[str, str] | None = None,
) -> tuple[str, Path]:
    """Runs the real generated watcher script for a bounded number of
    iterations against `stub_journalctl` (the full text of a stub
    `journalctl` executable placed first on PATH) and a fake crash
    directory. Returns (port_file_contents, crash_dir)."""
    script_path = _write_watcher(tmp_path)
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    _write_executable(stub_bin / "journalctl", stub_journalctl)

    port_file = tmp_path / "evidence-port"
    port_file.write_text("")
    crash_dir = tmp_path / "crash"
    crash_dir.mkdir()
    for name, content in (crash_files or {}).items():
        (crash_dir / name).write_text(content)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env.get('PATH', '')}"
    env["SEREIN_TEST_PORT"] = str(port_file)
    env["SEREIN_TEST_CRASH_DIR"] = str(crash_dir)
    env["SEREIN_QA_WATCHER_MAX_ITERATIONS"] = str(iterations)
    env["SEREIN_QA_WATCHER_SLEEP_SECONDS"] = "0"

    result = subprocess.run(
        ["sh", str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"watcher script exited non-zero: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    return port_file.read_text(), crash_dir


# A real Filesystem/_probe/probe_once cancellation line, verbatim in
# shape from real S7.1R21-TCG-REPRO-1 serial-log evidence (S7.1R21
# final report Section "TCG RUN": PROBE_CANCELLED at ~1286.4s).
_REAL_PROBE_CANCELLED_LINE = (
    "[ 1286.421944] subiquity_event.2686[2686]:  subiquity/Filesystem/_probe/"
    "probe_once: cancelled"
)
_REAL_DISK_PROBE_FAIL_LINE = (
    "[ 1601.612345] subiquity_event.2686[2686]:  subiquity/ErrorReporter/"
    "1789576841.999999999.disk_probe_fail/add_info: "
)


def _noise_lines(count: int, *, start_ts: float = 1.0) -> str:
    return "\n".join(
        f"[ {start_ts + i:.6f}] noise[1]: unrelated boot message number {i}"
        for i in range(count)
    )


class TestRealDefectRegression:
    """Section 14 (mandatory): reproduce the actual S7.1R21-TCG-REPRO-1
    failure mode against the OLD mechanism first, then prove the NEW
    mechanism catches it."""

    def test_old_shared_200_line_window_would_miss_the_real_trigger(self) -> None:
        """Ground truth for the regression: > 200 unrelated lines
        genuinely do scroll the real trigger line out of a plain
        `-n 200` snapshot - the exact real R21-TCG-REPRO-1 defect,
        reproduced here as pure text processing (no VM needed) so this
        test cannot silently stop meaning anything if the real bug
        were ever reintroduced elsewhere."""
        # The trigger fires, then MORE than 200 lines of unrelated
        # activity follow before the watcher's next poll snapshot -
        # exactly the real R21-TCG-REPRO-1 timeline (dense GNOME
        # session/os-prober noise after the cancellation).
        old_window_lines = (
            _REAL_PROBE_CANCELLED_LINE + "\n" + _noise_lines(260)
        ).splitlines()[-200:]
        # The real defect: the trigger line itself is gone entirely
        # once only the last 200 lines are kept.
        assert _REAL_PROBE_CANCELLED_LINE not in old_window_lines

    def test_cursor_mode_catches_the_real_trigger_despite_high_journal_volume(
        self, tmp_path: Path
    ) -> None:
        """The NEW mechanism: > 200 unrelated lines appear in the SAME
        poll as the real trigger line, and cursor mode must still
        catch it (never conveniently kept inside a small window - that
        would not regress-test the real defect, per Section 14's own
        explicit instruction)."""
        state_dir = tmp_path / "stub-state"
        state_dir.mkdir()
        # Noise lines are generated as real printf lines (never a
        # Python-side repr trick) so the stub text stays valid /bin/sh
        # regardless of what characters happen to be in them.
        noise_printfs = "\n".join(
            f'printf "%s\\n" "[ {1.0 + i:.6f}] noise[1]: unrelated boot message number {i}"'
            for i in range(260)
        )
        stub = f"""#!/bin/sh
STATE="{state_dir}/after_cursor_count"
has_n0=0
prev=""
for a in "$@"; do
    if [ "$prev" = "-n" ] && [ "$a" = "0" ]; then has_n0=1; fi
    prev="$a"
done
if [ "$has_n0" = "1" ]; then
    echo "-- No entries --"
    echo "-- cursor: CURSOR_A"
    exit 0
fi
has_after_cursor=0
for a in "$@"; do
    case "$a" in
        --after-cursor=*) has_after_cursor=1 ;;
    esac
done
if [ "$has_after_cursor" = "1" ]; then
    count=0
    [ -f "$STATE" ] && count=$(cat "$STATE")
    count=$((count + 1))
    echo "$count" > "$STATE"
    if [ "$count" = "1" ]; then
{noise_printfs}
        printf "%s\\n" "{_REAL_PROBE_CANCELLED_LINE}"
        echo "-- cursor: CURSOR_B"
    else
        echo "-- No entries --"
        echo "-- cursor: CURSOR_B"
    fi
    exit 0
fi
echo "-- No entries --"
"""
        port_contents, _ = _run_watcher(tmp_path, stub, iterations=2)
        assert "=== SEREIN STORAGE PROBE FRAME ===" in port_contents
        assert "trigger=probe_cancelled" in port_contents
        assert "trigger_source=journal_cursor" in port_contents
        assert "trigger_event_timestamp=1286.421944" in port_contents


class TestCrashFileDirectTrigger:
    """Section 15: block_probe_fail fires directly from crash-file
    existence, independent of any journal content."""

    _NO_ENTRIES_STUB = '#!/bin/sh\necho "-- No entries --"\n'

    def test_nonempty_crash_file_triggers_a_frame(self, tmp_path: Path) -> None:
        port_contents, _ = _run_watcher(
            tmp_path,
            self._NO_ENTRIES_STUB,
            iterations=1,
            crash_files={
                "1700000000.000000.block_probe_fail.crash": "some real crash body\n"
            },
        )
        assert "trigger=block_probe_fail" in port_contents
        assert "trigger_source=crash_file" in port_contents
        assert "trigger_event_timestamp=NOT_OBSERVED" in port_contents

    def test_zero_byte_crash_file_still_triggers_a_frame(self, tmp_path: Path) -> None:
        port_contents, _ = _run_watcher(
            tmp_path,
            self._NO_ENTRIES_STUB,
            iterations=1,
            crash_files={"1700000000.000000.block_probe_fail.crash": ""},
        )
        assert "trigger=block_probe_fail" in port_contents
        assert "trigger_source=crash_file" in port_contents
        # the OLD crash-evidence capture (a separate mechanism) must
        # still honestly record size=0 for the same file.
        assert "size=0" in port_contents


class TestDedup:
    """Section 16: repeated polls of the same real event must still
    only ever produce ONE frame per trigger."""

    def test_same_crash_file_across_multiple_polls_fires_once(
        self, tmp_path: Path
    ) -> None:
        stub = '#!/bin/sh\necho "-- No entries --"\n'
        port_contents, _ = _run_watcher(
            tmp_path,
            stub,
            iterations=4,
            crash_files={"x.block_probe_fail.crash": "body\n"},
        )
        assert port_contents.count("trigger=block_probe_fail") == 1

    def test_same_probe_cancellation_across_multiple_polls_fires_once(
        self, tmp_path: Path
    ) -> None:
        # The stub keeps returning the SAME trigger line on every
        # after-cursor poll (a real, busy guest may keep re-showing an
        # already-deduplicated earlier event too) - must still only
        # ever export one frame.
        stub = f"""#!/bin/sh
prev=""
has_n0=0
for a in "$@"; do
    if [ "$prev" = "-n" ] && [ "$a" = "0" ]; then has_n0=1; fi
    prev="$a"
done
if [ "$has_n0" = "1" ]; then
    echo "-- No entries --"
    echo "-- cursor: CURSOR_A"
    exit 0
fi
for a in "$@"; do
    case "$a" in
        --after-cursor=*)
            printf "%s\\n" "{_REAL_PROBE_CANCELLED_LINE}"
            echo "-- cursor: CURSOR_A"
            exit 0
            ;;
    esac
done
echo "-- No entries --"
"""
        port_contents, _ = _run_watcher(tmp_path, stub, iterations=4)
        assert port_contents.count("trigger=probe_cancelled") == 1


class TestCursorFallback:
    """Section 17: a journalctl with no cursor support must not crash
    the watcher, and must still be able to detect a trigger via the
    weaker bounded-window fallback."""

    def test_cursor_unsupported_falls_back_and_still_detects(
        self, tmp_path: Path
    ) -> None:
        # This stub NEVER emits a "-- cursor: " line at all (as if
        # this guest's journalctl predates cursor support) - the
        # watcher must fall back to STORAGE_TRIGGER_MODE=
        # bounded_window_fallback rather than aborting, and that
        # fallback window must still contain (and therefore detect) a
        # trigger line that genuinely is within it.
        stub = f"""#!/bin/sh
echo "-- No entries --"
printf "%s\\n" "{_REAL_PROBE_CANCELLED_LINE}"
"""
        port_contents, _ = _run_watcher(tmp_path, stub, iterations=1)
        assert "trigger=probe_cancelled" in port_contents
        assert "trigger_source=bounded_window_fallback" in port_contents


class TestFalsePositives:
    """Section 18: probe_once and cancelled must co-occur on the SAME
    line - two unrelated events must never combine into a false
    trigger."""

    def _stub_with_after_cursor_batch(self, batch: str) -> str:
        return f"""#!/bin/sh
prev=""
has_n0=0
for a in "$@"; do
    if [ "$prev" = "-n" ] && [ "$a" = "0" ]; then has_n0=1; fi
    prev="$a"
done
if [ "$has_n0" = "1" ]; then
    echo "-- No entries --"
    echo "-- cursor: CURSOR_A"
    exit 0
fi
for a in "$@"; do
    case "$a" in
        --after-cursor=*)
            {batch}
            echo "-- cursor: CURSOR_A"
            exit 0
            ;;
    esac
done
echo "-- No entries --"
"""

    def test_probe_once_without_cancelled_does_not_trigger(
        self, tmp_path: Path
    ) -> None:
        stub = self._stub_with_after_cursor_batch(
            'printf "%s\\n" "[ 100.0] subiquity_event: '
            'subiquity/Filesystem/_probe/probe_once: restricted=False"'
        )
        port_contents, _ = _run_watcher(tmp_path, stub, iterations=1)
        assert "trigger=probe_cancelled" not in port_contents

    def test_cancelled_on_an_unrelated_line_does_not_trigger(
        self, tmp_path: Path
    ) -> None:
        # "probe_once" on one line, an UNRELATED "cancelled" (e.g. a
        # generic systemd job cancellation) on a different line - must
        # never combine into a false storage-probe trigger.
        stub = self._stub_with_after_cursor_batch(
            'printf "%s\\n" "[ 100.0] subiquity_event: '
            'subiquity/Filesystem/_probe/probe_once: restricted=False"\n'
            '    printf "%s\\n" "[ 101.0] systemd[1]: Some unrelated job cancelled"'
        )
        port_contents, _ = _run_watcher(tmp_path, stub, iterations=1)
        assert "trigger=probe_cancelled" not in port_contents
