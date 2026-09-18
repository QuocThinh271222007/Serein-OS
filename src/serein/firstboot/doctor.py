"""``serein firstboot doctor``: read-only diagnostics (Section 32).

Mirrors ``serein.installer.doctor``'s philosophy: an absence that is
*expected* outside a real installed target (no handoff on this
development host, no systemd here) is PASS/SKIP, never FAIL. FAIL is
reserved for a genuinely broken structural state - malformed JSON in a
file that does exist, or plan/status construction itself raising.
Never mutates anything - even the lock-held probe
(:func:`serein.firstboot.lock.is_lock_held`) releases immediately.
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT

from .eligibility import evaluate_eligibility
from .lock import is_lock_held
from .models import FIRSTBOOT_LOCK_RELATIVE_PATH, FIRSTBOOT_STATE_RELATIVE_PATH, FIRSTBOOT_STATES
from .statefile import FirstbootStateStore

_HANDOFF_CHECK = ("firstboot_handoff_present", "S7.1 handoff (install-state.json) presence")
_HANDOFF_VALID_CHECK = ("firstboot_handoff_valid", "S7.1 handoff structural validity")
_STATE_CHECK = ("firstboot_state_readable", "First-boot state file readability")
_LOCK_CHECK = ("firstboot_lock_available", "First-boot concurrency lock availability")
_LIVE_MEDIA_CHECK = ("firstboot_live_media", "Live-media environment detection")
_SYSTEMD_CHECK = ("firstboot_systemd_unit", "serein-firstboot.service availability")


def _check_handoff(root: Path) -> tuple[CheckResult, CheckResult]:
    eligibility = evaluate_eligibility(root)
    install_state = eligibility.install_state

    present_id, present_title = _HANDOFF_CHECK
    if not install_state.present:
        present_check = CheckResult(
            present_id, present_title, CheckStatus.SKIP,
            "No /etc/serein/install-state.json - expected outside a real S7.1-installed "
            "target (e.g. this development host or CI).",
        )
    else:
        present_check = CheckResult(
            present_id, present_title, CheckStatus.PASS, "install-state.json is present."
        )

    valid_id, valid_title = _HANDOFF_VALID_CHECK
    if not install_state.present:
        valid_check = CheckResult(
            valid_id, valid_title, CheckStatus.SKIP, "No handoff file to validate."
        )
    elif not install_state.valid:
        valid_check = CheckResult(
            valid_id, valid_title, CheckStatus.FAIL,
            f"install-state.json is present but malformed: {install_state.error}",
        )
    else:
        marker = install_state.marker
        assert marker is not None
        valid_check = CheckResult(
            valid_id, valid_title, CheckStatus.PASS,
            f"install-state.json is valid "
            f"(firstboot_provisioning={marker.firstboot_provisioning!r}).",
        )

    return present_check, valid_check


def _check_state(root: Path) -> CheckResult:
    check_id, title = _STATE_CHECK
    store = FirstbootStateStore(root / FIRSTBOOT_STATE_RELATIVE_PATH)
    state, error = store.load_corrupt_safe()
    if error is not None:
        return CheckResult(check_id, title, CheckStatus.FAIL, error)
    if state is None:
        return CheckResult(
            check_id, title, CheckStatus.SKIP, "No first-boot state file yet - not started."
        )
    if state.state not in FIRSTBOOT_STATES:
        return CheckResult(
            check_id, title, CheckStatus.FAIL,
            f"state.json carries an unrecognized state {state.state!r}.",
        )
    if state.state == "complete":
        return CheckResult(
            check_id, title, CheckStatus.PASS, "First-boot provisioning already complete."
        )
    return CheckResult(
        check_id, title, CheckStatus.PASS, f"State file readable (state={state.state})."
    )


def _check_lock(root: Path) -> CheckResult:
    check_id, title = _LOCK_CHECK
    lock_path = root / FIRSTBOOT_LOCK_RELATIVE_PATH
    if is_lock_held(lock_path):
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "The first-boot lock is currently held - a provisioning run is in progress "
            "(or a stale lock from a crashed run needs administrative attention).",
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "Lock is available.")


def _check_live_media(root: Path) -> CheckResult:
    check_id, title = _LIVE_MEDIA_CHECK
    eligibility = evaluate_eligibility(root)
    if eligibility.live_media.is_live_media:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            f"Live-media environment detected - provisioning is blocked ({eligibility.reason}).",
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "No live-media evidence observed.")


def _check_systemd_unit(runner: CommandRunner) -> CheckResult:
    check_id, title = _SYSTEMD_CHECK
    result = runner.run(["systemctl", "is-enabled", "serein-firstboot.service"])
    if result is None:
        return CheckResult(
            check_id, title, CheckStatus.SKIP,
            "systemctl not found - expected outside a real systemd host.",
        )
    if result.returncode == 0:
        return CheckResult(
            check_id, title, CheckStatus.PASS, "serein-firstboot.service is enabled."
        )
    return CheckResult(
        check_id, title, CheckStatus.SKIP,
        "serein-firstboot.service is not enabled/known to systemd on this host - "
        "expected until distribution packaging installs the unit (see known-limitations).",
    )


def run_firstboot_checks(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> DoctorReport:
    present_check, valid_check = _check_handoff(root)
    checks = [
        present_check,
        valid_check,
        _check_state(root),
        _check_lock(root),
        _check_live_media(root),
        _check_systemd_unit(runner),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
