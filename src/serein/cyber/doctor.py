"""``serein cyber doctor``: cybersecurity-layer diagnostics.

Reuses ``serein.doctor.models`` (same PASS/WARN/FAIL/SKIP model as
S0-S4's doctors). No cyber tooling installed is PASS, never FAIL
(Section 24) — host-heavy tooling found on the host, a partial
Wireshark/dumpcap install, or two container engines are all WARN
territory, never FAIL. FAIL is reserved for a genuinely broken
structural state (a manifest that fails to parse, plan generation
raising), which S5 cannot currently produce either since there is no
Apply/managed-state mechanism yet.
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.cyber.capture import detect_capture_status
from serein.cyber.models import CYBER_TIERS
from serein.cyber.planner import VALID_COMPONENTS, build_cyber_plan
from serein.cyber.toolbox import detect_host_hygiene, detect_toolbox_status
from serein.cyber.tools import all_tools
from serein.development.models import ToolSourceType
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT
from serein.profiles.registry import DEFAULT_PROFILES_DIR

_PROFILE_CHECK = ("cyber_profile_integrity", "Cyber profile integrity")
_MANIFEST_CHECK = ("cyber_package_manifest", "Cyber tool manifest integrity")
_PLAN_CHECK = ("cyber_plan_generation", "Cyber plan generation")
_HYGIENE_CHECK = ("cyber_host_hygiene", "Host-heavy tooling on the daily host")
_CAPTURE_CHECK = ("cyber_capture_backend_consistency", "Packet capture backend consistency")
_CONTAINER_ENGINE_CHECK = ("cyber_container_engine_conflict", "Toolbox container engine conflicts")

_VALID_SOURCE_TYPES: set[ToolSourceType] = {
    "ubuntu-repository", "official-upstream-repository", "official-upstream-binary",
    "language-bootstrap-tool", "user-installed", "optional", "python-package-index",
}


def _check_profile_integrity() -> CheckResult:
    check_id, title = _PROFILE_CHECK
    manifest_path = DEFAULT_PROFILES_DIR / "cyber" / "cyber.profile.json"
    if not manifest_path.is_file():
        detail = "profiles/cyber/cyber.profile.json is missing."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    try:
        json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        detail = f"cyber.profile.json is not valid JSON: {exc}"
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "cyber.profile.json parses.")


def _check_manifest() -> CheckResult:
    check_id, title = _MANIFEST_CHECK
    tools = all_tools()
    ids = [t.id for t in tools]
    if len(ids) != len(set(ids)):
        detail = "Duplicate tool ids in the cyber manifest."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    unrecognized_source = [t.id for t in tools if t.source_type not in _VALID_SOURCE_TYPES]
    if unrecognized_source:
        detail = f"Unrecognized source_type for: {', '.join(unrecognized_source)}."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    unrecognized_tier = [t.id for t in tools if t.recommended_tier not in CYBER_TIERS]
    if unrecognized_tier:
        detail = f"Unrecognized recommended_tier for: {', '.join(unrecognized_tier)}."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, f"{len(tools)} tool(s) declared.")


def _check_plan_generation(root: Path, runner: CommandRunner) -> CheckResult:
    check_id, title = _PLAN_CHECK
    try:
        build_cyber_plan(root=root, runner=runner)
        for component in VALID_COMPONENTS:
            build_cyber_plan(component, root=root, runner=runner)
    except Exception as exc:
        return CheckResult(check_id, title, CheckStatus.FAIL, f"Plan generation raised: {exc}")
    detail = f"Full plan and all {len(VALID_COMPONENTS)} component plans generated without error."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_host_hygiene(runner: CommandRunner) -> CheckResult:
    check_id, title = _HYGIENE_CHECK
    hygiene = detect_host_hygiene(runner=runner)
    found = [
        t.id for t in (hygiene.hashcat, hygiene.john, hygiene.metasploit,
                        hygiene.sqlmap, hygiene.aircrack_ng)
        if t.installed
    ]
    if found:
        detail = (
            f"Toolbox/VM-tier tool(s) found on the host: {', '.join(found)}. "
            "Not necessarily wrong (a user may have installed them "
            "deliberately) - Serein never removes anything, this is "
            "informational only."
        )
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "No host-heavy cyber tooling detected.")


def _check_capture_backend_consistency(runner: CommandRunner) -> CheckResult:
    check_id, title = _CAPTURE_CHECK
    capture = detect_capture_status(runner=runner)
    gui_or_cli_present = capture.wireshark.installed or capture.tshark.installed
    if gui_or_cli_present and not capture.dumpcap.installed:
        detail = (
            "wireshark/tshark is installed but dumpcap is not - a partial "
            "or broken capture-tooling install (dumpcap is the shared "
            "capture backend both depend on)."
        )
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    detail = "No capture-backend inconsistency detected."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_container_engine_conflict(runner: CommandRunner) -> CheckResult:
    check_id, title = _CONTAINER_ENGINE_CHECK
    containers = detect_toolbox_status(runner=runner)
    if containers.podman.installed and containers.docker.installed:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "Both Podman and Docker are installed; Serein will not choose one for you.",
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "No conflicting container engines.")


def run_cyber_checks(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> DoctorReport:
    checks = [
        _check_profile_integrity(),
        _check_manifest(),
        _check_plan_generation(root, runner),
        _check_host_hygiene(runner),
        _check_capture_backend_consistency(runner),
        _check_container_engine_conflict(runner),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
