"""Desktop-level diagnostic checks.

Reuses ``serein.doctor.models`` (same ``PASS``/``WARN``/``FAIL``/``SKIP``
result model and ``DoctorReport`` shape as the S0 foundation doctor), so
``serein desktop doctor --json`` validates against the same
``schemas/doctor-report.schema.json`` with no new schema needed.

Every check takes ``(root, env)`` for a uniform signature even when one
argument is unused, matching the convention in
``serein.doctor.checks``. See ``docs/architecture/doctor-contract.md``
and ``docs/desktop/architecture.md`` for the installed/running/managed
distinction that drives ``_component_check``.
"""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Mapping
from pathlib import Path

from serein.desktop.config import RESOURCES, missing_resources
from serein.desktop.detect import detect_availability, detect_config_state, detect_session
from serein.desktop.models import TARGET_UBUNTU_VERSION
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT, is_real_root
from serein.hardware.os_release import read_os_release
from serein.profiles.registry import DEFAULT_PROFILES_DIR

_REPO_ROOT = Path(__file__).resolve().parents[3]

_OS_CHECK = ("desktop_os_compatibility", "Desktop OS compatibility")
_PLASMA_CHECK = ("desktop_plasma_availability", "Plasma availability")
_KWIN_CHECK = ("desktop_kwin_availability", "KWin availability")
_SDDM_CHECK = ("desktop_sddm_availability", "SDDM availability")
_WAYLAND_CHECK = ("desktop_wayland_session", "Wayland session")
_CONTRACT_CHECK = ("desktop_config_contract", "Desktop config contract")
_RESOURCES_CHECK = ("desktop_required_resources", "Desktop config resources present")


def _component_check(
    check: tuple[str, str], marker_present: bool, component_present: bool
) -> CheckResult:
    check_id, title = check
    if not marker_present and not component_present:
        detail = "Serein Desktop has not been applied to this host yet."
        return CheckResult(check_id, title, CheckStatus.SKIP, detail)
    if not marker_present and component_present:
        detail = "Component detected but not Serein-managed (no config-version marker)."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    if marker_present and component_present:
        detail = "Component present and Serein-managed."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    detail = "Serein config marker present but component missing: broken installation."
    return CheckResult(check_id, title, CheckStatus.FAIL, detail)


def _check_os_compatibility(root: Path, _env: Mapping[str, str]) -> CheckResult:
    check_id, title = _OS_CHECK
    if platform.system() != "Linux" and is_real_root(root):
        return CheckResult(check_id, title, CheckStatus.SKIP, "Not applicable off Linux.")
    os_info = read_os_release(root)
    if not os_info.id:
        detail = "No /etc/os-release found; compatibility unknown."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    if not os_info.is_ubuntu:
        detail = f"Non-Ubuntu OS detected ({os_info.pretty_name or os_info.id}); untested."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    if os_info.version_id == TARGET_UBUNTU_VERSION:
        detail = f"Ubuntu {TARGET_UBUNTU_VERSION} detected (Serein Desktop's target release)."
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    detail = (
        f"Ubuntu {os_info.version_id or 'unknown version'} detected; "
        f"Serein Desktop targets {TARGET_UBUNTU_VERSION} and this release is untested."
    )
    return CheckResult(check_id, title, CheckStatus.WARN, detail)


def _check_plasma(root: Path, _env: Mapping[str, str]) -> CheckResult:
    availability = detect_availability(root)
    config = detect_config_state(root)
    return _component_check(
        _PLASMA_CHECK, config.serein_preset_applied, availability.plasma_installed
    )


def _check_kwin(root: Path, _env: Mapping[str, str]) -> CheckResult:
    availability = detect_availability(root)
    config = detect_config_state(root)
    kwin_present = availability.kwin_wayland_installed or availability.kwin_x11_installed
    return _component_check(_KWIN_CHECK, config.serein_preset_applied, kwin_present)


def _check_sddm(root: Path, _env: Mapping[str, str]) -> CheckResult:
    availability = detect_availability(root)
    config = detect_config_state(root)
    return _component_check(_SDDM_CHECK, config.serein_preset_applied, availability.sddm_installed)


def _check_wayland_session(_root: Path, env: Mapping[str, str]) -> CheckResult:
    check_id, title = _WAYLAND_CHECK
    session = detect_session(env)
    if session.session_type is None:
        detail = "No graphical session detected (headless/CLI context)."
        return CheckResult(check_id, title, CheckStatus.SKIP, detail)
    if session.session_type == "wayland":
        return CheckResult(check_id, title, CheckStatus.PASS, "Wayland session active.")
    detail = "X11 session active; Wayland is Serein's preferred session type."
    return CheckResult(check_id, title, CheckStatus.WARN, detail)


def _check_config_contract(_root: Path, _env: Mapping[str, str]) -> CheckResult:
    check_id, title = _CONTRACT_CHECK
    profile_path = DEFAULT_PROFILES_DIR / "desktop" / "desktop.profile.json"
    schema_paths = [
        _REPO_ROOT / "schemas" / "desktop-plan.schema.json",
        _REPO_ROOT / "schemas" / "desktop-state.schema.json",
    ]
    if not profile_path.is_file():
        detail = "profiles/desktop/desktop.profile.json is missing."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    for path in [profile_path, *schema_paths]:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            detail = f"{path.name} is not valid JSON: {exc}"
            return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "Desktop profile and schemas parse.")


def _check_required_resources(_root: Path, _env: Mapping[str, str]) -> CheckResult:
    check_id, title = _RESOURCES_CHECK
    missing = missing_resources()
    if missing:
        names = ", ".join(r.id for r in missing)
        detail = f"Missing shipped resource(s): {names}."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    detail = f"All {len(RESOURCES)} shipped resources present."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


_ALL_CHECKS = (
    _check_os_compatibility,
    _check_plasma,
    _check_kwin,
    _check_sddm,
    _check_wayland_session,
    _check_config_contract,
    _check_required_resources,
)


def run_desktop_checks(
    root: Path = DEFAULT_ROOT, env: Mapping[str, str] | None = None
) -> DoctorReport:
    effective_env = env if env is not None else os.environ
    checks = [check(root, effective_env) for check in _ALL_CHECKS]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
