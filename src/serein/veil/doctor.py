"""``serein veil doctor``: Veil-layer diagnostics.

Reuses ``serein.doctor.models`` (same PASS/WARN/FAIL/SKIP model as
S0-S5's doctors). No Tor/Whonix tooling installed is PASS/SKIP, never
FAIL (Section 49) - privacy tooling is entirely optional. FAIL is
reserved for a genuinely broken structural state (a manifest that fails
to parse, plan generation raising); a workspace explicitly claiming
"Tor-only" while configured for direct clearnet egress would also be
FAIL, but S6 has no mechanism to create such managed state yet, so that
class of failure cannot currently occur (Section 50).
"""

from __future__ import annotations

from pathlib import Path

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.doctor.models import SCHEMA_VERSION, CheckResult, CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT
from serein.veil.browser import detect_tor_browser_status
from serein.veil.components import all_components
from serein.veil.models import VEIL_CATEGORIES, VEIL_TIERS
from serein.veil.planner import VALID_COMPONENTS, build_veil_plan
from serein.veil.tor import detect_tor_status
from serein.veil.whonix import detect_whonix_status

_MANIFEST_CHECK = ("veil_component_manifest", "Veil component manifest integrity")
_PLAN_CHECK = ("veil_plan_generation", "Veil plan generation")
_TOR_SERVICE_CHECK = ("veil_tor_package_service_mismatch", "Tor package/service consistency")
_TOR_SOCKS_CHECK = (
    "veil_tor_socks_configured_service_inactive", "Tor SOCKS configuration/service consistency",
)
_WORKSPACE_CHECK = ("veil_workspace_isolation", "Private workspace isolation mechanism")
_TOR_ONLY_CLAIM_CHECK = (
    "veil_tor_only_claim_kill_switch", "Tor-only claim/kill-switch consistency",
)
_TOR_BROWSER_CHECK = ("veil_tor_browser_availability", "Tor Browser availability")
_WHONIX_BACKEND_CHECK = ("veil_whonix_backend_readiness", "Whonix VM backend readiness")
_WHONIX_IMAGES_CHECK = ("veil_whonix_images_partial", "Whonix Gateway/Workstation image presence")

_VALID_SOURCE_TYPES = {"ubuntu-repository", "user-managed"}


def _check_manifest() -> CheckResult:
    check_id, title = _MANIFEST_CHECK
    components = all_components()
    ids = [c.id for c in components]
    if len(ids) != len(set(ids)):
        return CheckResult(
            check_id, title, CheckStatus.FAIL, "Duplicate component ids in the veil manifest."
        )
    bad_source = [c.id for c in components if c.source_type not in _VALID_SOURCE_TYPES]
    if bad_source:
        return CheckResult(
            check_id, title, CheckStatus.FAIL,
            f"Unrecognized source_type for: {', '.join(bad_source)}.",
        )
    bad_tier = [c.id for c in components if c.recommended_tier not in VEIL_TIERS]
    if bad_tier:
        return CheckResult(
            check_id, title, CheckStatus.FAIL,
            f"Unrecognized recommended_tier for: {', '.join(bad_tier)}.",
        )
    bad_category = [c.id for c in components if c.category not in VEIL_CATEGORIES]
    if bad_category:
        return CheckResult(
            check_id, title, CheckStatus.FAIL,
            f"Unrecognized category for: {', '.join(bad_category)}.",
        )
    detail = f"{len(components)} component(s) declared."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_plan_generation(root: Path, runner: CommandRunner, home: Path | None) -> CheckResult:
    check_id, title = _PLAN_CHECK
    try:
        build_veil_plan(root=root, runner=runner, home=home)
        for component in VALID_COMPONENTS:
            build_veil_plan(component, root=root, runner=runner, home=home)
    except Exception as exc:
        return CheckResult(check_id, title, CheckStatus.FAIL, f"Plan generation raised: {exc}")
    detail = f"Full plan and all {len(VALID_COMPONENTS)} component plans generated without error."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_tor_service_consistency(runner: CommandRunner, root: Path) -> CheckResult:
    check_id, title = _TOR_SERVICE_CHECK
    tor = detect_tor_status(runner=runner, root=root)
    if tor.package_installed and tor.service_present is False:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "The tor package is installed but no tor systemd service unit "
            "was found - a partial or non-systemd install; Tor client "
            "usability may be affected.",
        )
    detail = "No tor package/service mismatch detected."
    return CheckResult(check_id, title, CheckStatus.PASS, detail)


def _check_tor_socks_consistency(runner: CommandRunner, root: Path) -> CheckResult:
    check_id, title = _TOR_SOCKS_CHECK
    tor = detect_tor_status(runner=runner, root=root)
    if tor.config.socks_port_configured is True and tor.service_active is False:
        return CheckResult(
            check_id, title, CheckStatus.WARN,
            "torrc explicitly configures a SocksPort, but the tor service "
            "is not active - the configured SOCKS listener is not "
            "actually running.",
        )
    return CheckResult(
        check_id, title, CheckStatus.PASS, "No SOCKS configuration/service mismatch detected."
    )


def _check_workspace_isolation(runner: CommandRunner, root: Path) -> CheckResult:
    check_id, title = _WORKSPACE_CHECK
    tor = detect_tor_status(runner=runner, root=root)
    if tor.usable is not True:
        return CheckResult(
            check_id, title, CheckStatus.SKIP,
            "Tor client usability is not confirmed; no privacy workspace "
            "isolation state to evaluate.",
        )
    return CheckResult(
        check_id, title, CheckStatus.WARN,
        "Tor client is usable, but S6 has no Apply engine and has not "
        "configured any isolated workspace boundary (namespace/container/"
        "browser profile) - informational, not a defect: an isolated "
        "workspace is planned but never provisioned by this phase "
        "(Section 5/78-79).",
    )


def _check_tor_only_claim() -> CheckResult:
    check_id, title = _TOR_ONLY_CLAIM_CHECK
    return CheckResult(
        check_id, title, CheckStatus.PASS,
        "S6 has no mechanism to mark a workspace as 'Tor-only' yet, so a "
        "workspace claiming Tor-only routing while actually configured for "
        "direct clearnet egress cannot currently occur; reserved as a "
        "future FAIL condition once an Apply engine exists (Section 50).",
    )


def _check_tor_browser_availability(runner: CommandRunner) -> CheckResult:
    check_id, title = _TOR_BROWSER_CHECK
    status = detect_tor_browser_status(runner=runner)
    if not status.launcher_installed:
        return CheckResult(
            check_id, title, CheckStatus.SKIP,
            "torbrowser-launcher is not installed - fully optional, headless"
            " hosts are expected to skip this (Section 84).",
        )
    return CheckResult(check_id, title, CheckStatus.PASS, "torbrowser-launcher is installed.")


def _check_whonix_backend(runner: CommandRunner, root: Path, home: Path | None) -> CheckResult:
    check_id, title = _WHONIX_BACKEND_CHECK
    whonix = detect_whonix_status(runner=runner, root=root, home=home)
    readiness = whonix.vm_readiness
    if readiness.status == "blocked_no_hardware":
        return CheckResult(check_id, title, CheckStatus.SKIP, readiness.reason)
    if readiness.status == "ready":
        return CheckResult(check_id, title, CheckStatus.PASS, readiness.reason)
    return CheckResult(check_id, title, CheckStatus.WARN, readiness.reason)


def _check_whonix_images(runner: CommandRunner, root: Path, home: Path | None) -> CheckResult:
    check_id, title = _WHONIX_IMAGES_CHECK
    whonix = detect_whonix_status(runner=runner, root=root, home=home)
    gateway, workstation = whonix.gateway_image_present, whonix.workstation_image_present
    if gateway == workstation:
        detail = (
            "Both Whonix images are present." if gateway
            else "Neither Whonix image is present - expected on most hosts."
        )
        return CheckResult(check_id, title, CheckStatus.PASS, detail)
    missing = "Workstation" if gateway else "Gateway"
    return CheckResult(
        check_id, title, CheckStatus.WARN,
        f"Only one Whonix image is present (missing: {missing}) - an "
        "incomplete Gateway+Workstation pair cannot form the canonical "
        "Whonix topology (Section 25/32).",
    )


def run_veil_checks(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER, home: Path | None = None
) -> DoctorReport:
    checks = [
        _check_manifest(),
        _check_plan_generation(root, runner, home),
        _check_tor_service_consistency(runner, root),
        _check_tor_socks_consistency(runner, root),
        _check_workspace_isolation(runner, root),
        _check_tor_only_claim(),
        _check_tor_browser_availability(runner),
        _check_whonix_backend(runner, root, home),
        _check_whonix_images(runner, root, home),
    ]
    return DoctorReport(schema_version=SCHEMA_VERSION, checks=checks)
