"""Schema contract tests: schema files are valid, and real output from the
tool validates against them."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from serein.ai.capabilities import build_ai_capabilities
from serein.ai.doctor import run_ai_checks
from serein.ai.planner import VALID_COMPONENTS as AI_VALID_COMPONENTS
from serein.ai.planner import build_ai_plan
from serein.cyber.capabilities import build_cyber_capabilities
from serein.cyber.doctor import run_cyber_checks
from serein.cyber.planner import VALID_COMPONENTS as CYBER_VALID_COMPONENTS
from serein.cyber.planner import build_cyber_plan
from serein.desktop.doctor import run_desktop_checks
from serein.desktop.plan import build_desktop_plan
from serein.desktop.status import build_desktop_status
from serein.development.capabilities import build_development_capabilities
from serein.development.doctor import run_development_checks
from serein.development.planner import VALID_COMPONENTS as DEV_VALID_COMPONENTS
from serein.development.planner import build_development_plan
from serein.doctor.checks import run_checks
from serein.hardware.capabilities import build_capabilities
from serein.hardware.doctor import run_hardware_checks
from serein.hardware.planner import VALID_PROFILES, build_hardware_plan
from serein.hardware.probe import probe_hardware
from serein.profiles.models import ProfileManifest
from serein.veil.capabilities import build_veil_capabilities
from serein.veil.doctor import run_veil_checks
from serein.veil.planner import VALID_COMPONENTS as VEIL_VALID_COMPONENTS
from serein.veil.planner import build_veil_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "hardware-report.schema.json",
        "doctor-report.schema.json",
        "profile.schema.json",
        "desktop-plan.schema.json",
        "desktop-state.schema.json",
        "hardware-plan.schema.json",
        "hardware-capabilities.schema.json",
        "development-plan.schema.json",
        "development-capabilities.schema.json",
        "ai-plan.schema.json",
        "ai-capabilities.schema.json",
        "cyber-plan.schema.json",
        "cyber-capabilities.schema.json",
        "veil-plan.schema.json",
        "veil-capabilities.schema.json",
    ],
)
def test_schema_file_is_valid_json_schema(name: str) -> None:
    schema = _load_schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)


def test_hardware_report_validates_against_schema(host_root) -> None:
    schema = _load_schema("hardware-report.schema.json")
    report = probe_hardware(host_root("nvidia_workstation"))
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_hardware_report_validates_for_missing_data(host_root) -> None:
    schema = _load_schema("hardware-report.schema.json")
    report = probe_hardware(host_root("missing_data"))
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_doctor_report_validates_against_schema(host_root) -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_checks(host_root("amd_desktop"))
    jsonschema.validate(instance=report.to_dict(), schema=schema)


@pytest.mark.parametrize(
    "profile_id", ["core", "desktop", "balanced", "dev", "ai", "battery", "cyber"]
)
def test_profile_manifest_validates_against_schema(profile_id: str) -> None:
    schema = _load_schema("profile.schema.json")
    manifest_path = REPO_ROOT / "profiles" / profile_id / f"{profile_id}.profile.json"
    data = json.loads(manifest_path.read_text())
    jsonschema.validate(instance=data, schema=schema)
    # Also confirm it round-trips through our own model shape.
    manifest = ProfileManifest.from_dict(data)
    jsonschema.validate(instance=manifest.to_dict(), schema=schema)


def test_desktop_plan_validates_against_schema() -> None:
    schema = _load_schema("desktop-plan.schema.json")
    jsonschema.validate(instance=build_desktop_plan().to_dict(), schema=schema)


def test_desktop_status_validates_against_schema(host_root) -> None:
    schema = _load_schema("desktop-state.schema.json")
    status = build_desktop_status(root=host_root("plasma_wayland_managed"), env={})
    jsonschema.validate(instance=status.to_dict(), schema=schema)


def test_desktop_status_validates_for_missing_data(host_root) -> None:
    schema = _load_schema("desktop-state.schema.json")
    status = build_desktop_status(root=host_root("missing_data"), env={})
    jsonschema.validate(instance=status.to_dict(), schema=schema)


def test_desktop_doctor_report_validates_against_schema(host_root) -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_desktop_checks(host_root("amd_desktop"), env={})
    jsonschema.validate(instance=report.to_dict(), schema=schema)


@pytest.mark.parametrize("profile_id", list(VALID_PROFILES))
def test_hardware_plan_validates_against_schema(host_root, profile_id: str) -> None:
    schema = _load_schema("hardware-plan.schema.json")
    plan = build_hardware_plan(profile_id, host_root("nvidia_workstation"))
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


def test_hardware_plan_validates_for_missing_data(host_root) -> None:
    schema = _load_schema("hardware-plan.schema.json")
    root = host_root("missing_data")
    for profile_id in VALID_PROFILES:
        plan = build_hardware_plan(profile_id, root)
        jsonschema.validate(instance=plan.to_dict(), schema=schema)


def test_hardware_capabilities_validates_against_schema(host_root) -> None:
    schema = _load_schema("hardware-capabilities.schema.json")
    report = build_capabilities(host_root("amd_desktop"))
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_hardware_doctor_report_validates_against_schema(host_root) -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_hardware_checks(host_root("amd_desktop"))
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_development_capabilities_validates_against_schema() -> None:
    schema = _load_schema("development-capabilities.schema.json")
    report = build_development_capabilities()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_development_plan_validates_against_schema() -> None:
    schema = _load_schema("development-plan.schema.json")
    plan = build_development_plan()
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


@pytest.mark.parametrize("component", list(DEV_VALID_COMPONENTS))
def test_development_focused_plan_validates_against_schema(component: str) -> None:
    schema = _load_schema("development-plan.schema.json")
    plan = build_development_plan(component)
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


def test_development_doctor_report_validates_against_schema() -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_development_checks()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_ai_capabilities_validates_against_schema() -> None:
    schema = _load_schema("ai-capabilities.schema.json")
    report = build_ai_capabilities()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_ai_plan_validates_against_schema() -> None:
    schema = _load_schema("ai-plan.schema.json")
    plan = build_ai_plan()
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


@pytest.mark.parametrize("component", list(AI_VALID_COMPONENTS))
def test_ai_focused_plan_validates_against_schema(component: str) -> None:
    schema = _load_schema("ai-plan.schema.json")
    plan = build_ai_plan(component)
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


def test_ai_doctor_report_validates_against_schema() -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_ai_checks()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_cyber_capabilities_validates_against_schema() -> None:
    schema = _load_schema("cyber-capabilities.schema.json")
    report = build_cyber_capabilities()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_cyber_plan_validates_against_schema() -> None:
    schema = _load_schema("cyber-plan.schema.json")
    plan = build_cyber_plan()
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


@pytest.mark.parametrize("component", list(CYBER_VALID_COMPONENTS))
def test_cyber_focused_plan_validates_against_schema(component: str) -> None:
    schema = _load_schema("cyber-plan.schema.json")
    plan = build_cyber_plan(component)
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


def test_cyber_doctor_report_validates_against_schema() -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_cyber_checks()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_veil_capabilities_validates_against_schema() -> None:
    schema = _load_schema("veil-capabilities.schema.json")
    report = build_veil_capabilities()
    jsonschema.validate(instance=report.to_dict(), schema=schema)


def test_veil_plan_validates_against_schema() -> None:
    schema = _load_schema("veil-plan.schema.json")
    plan = build_veil_plan()
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


@pytest.mark.parametrize("component", list(VEIL_VALID_COMPONENTS))
def test_veil_focused_plan_validates_against_schema(component: str) -> None:
    schema = _load_schema("veil-plan.schema.json")
    plan = build_veil_plan(component)
    jsonschema.validate(instance=plan.to_dict(), schema=schema)


def test_veil_doctor_report_validates_against_schema() -> None:
    schema = _load_schema("doctor-report.schema.json")
    report = run_veil_checks()
    jsonschema.validate(instance=report.to_dict(), schema=schema)
