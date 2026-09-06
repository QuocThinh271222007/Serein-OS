"""``serein dev doctor``: development-layer diagnostics.

Reuses ``serein.doctor.models`` (same PASS/WARN/FAIL/SKIP model as the
S0/S1/S2 doctors), so ``--json`` validates against the existing
``schemas/doctor-report.schema.json``. Coexisting tool managers (two
Node managers, two container engines) are WARN, never FAIL — Serein
does not consider user tool choices "broken" (docs/development/
known-limitations.md). FAIL is reserved for genuine structural defects
(a manifest that fails to parse, plan generation raising).
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.development.containers import detect_container_status
from serein.development.node import detect_node_status
from serein.development.packages import all_tools, default_apt_packages
from serein.development.planner import VALID_COMPONENTS, build_development_plan
from serein.development.resources import RESOURCES, missing_resources
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.profiles.registry import DEFAULT_PROFILES_DIR

_MANIFEST_CHECK = ("development_package_manifest", "Development package manifest integrity")
_RESOURCES_CHECK = ("development_required_resources", "Development config resources present")
_PLAN_CHECK = ("development_plan_generation", "Development plan generation")
_NODE_CONFLICT_CHECK = ("development_node_manager_conflict", "Node version-manager conflicts")
_CONTAINER_CONFLICT_CHECK = ("development_container_engine_conflict", "Container engine conflicts")
_PROFILE_CHECK = ("development_profile_integrity", "Development profile integrity")


def _check_manifest() -> CheckResult:
    check_id, title = _MANIFEST_CHECK
    tools = all_tools()
    ids = [t.id for t in tools]
    if len(ids) != len(set(ids)):
        return CheckResult(check_id, title, CheckStatus.FAIL, "Duplicate tool ids in the manifest.")
    if not default_apt_packages():
        return CheckResult(check_id, title, CheckStatus.FAIL, "Default apt package list is empty.")
    detail = f"{len(tools)} tool(s) declared, {len(default_apt_packages())} default apt package(s)."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_resources() -> CheckResult:
    check_id, title = _RESOURCES_CHECK
    missing = missing_resources()
    if missing:
        names = ", ".join(r.id for r in missing)
        detail = f"Missing shipped resource(s): {names}."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    detail = f"All {len(RESOURCES)} shipped resources present."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_plan_generation(runner: CommandRunner, home: Path | None) -> CheckResult:
    check_id, title = _PLAN_CHECK
    try:
        build_development_plan(runner=runner, home=home)
        for component in VALID_COMPONENTS:
            build_development_plan(component, runner=runner, home=home)
    except Exception as exc:
        return CheckResult(check_id, title, CheckStatus.FAIL, f"Plan generation raised: {exc}")
    detail = f"Full plan and all {len(VALID_COMPONENTS)} component plans generated without error."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_node_conflicts(runner: CommandRunner, home: Path | None) -> CheckResult:
    check_id, title = _NODE_CONFLICT_CHECK
    node_status = detect_node_status(runner, home)
    if node_status.manager_count > 1:
        detail = f"Multiple Node version managers detected ({', '.join(node_status.managers)})."
        return CheckResult(check_id, title, CheckStatus.WARN, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "No conflicting Node version managers.")


def _check_container_conflicts(runner: CommandRunner) -> CheckResult:
    check_id, title = _CONTAINER_CONFLICT_CHECK
    containers = detect_container_status(runner)
    if containers.podman.installed and containers.docker.installed:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "Both Podman and Docker are installed; Serein will not choose one for you.",
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "No conflicting container engines.")


def _check_profile_integrity() -> CheckResult:
    check_id, title = _PROFILE_CHECK
    manifest_path = DEFAULT_PROFILES_DIR / "dev" / "dev.profile.json"
    if not manifest_path.is_file():
        detail = "profiles/dev/dev.profile.json is missing."
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    try:
        json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        detail = f"dev.profile.json is not valid JSON: {exc}"
        return CheckResult(check_id, title, CheckStatus.FAIL, detail)
    return CheckResult(check_id, title, CheckStatus.PASS, "dev.profile.json parses.")


def run_development_checks(
    runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> DoctorReport:
    checks = [
        _check_profile_integrity(),
        _check_manifest(),
        _check_resources(),
        _check_plan_generation(runner, home),
        _check_node_conflicts(runner, home),
        _check_container_conflicts(runner),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
