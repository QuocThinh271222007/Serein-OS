"""Schema contract tests: schema files are valid, and real output from the
tool validates against them."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from serein.desktop.doctor import run_desktop_checks
from serein.desktop.plan import build_desktop_plan
from serein.desktop.status import build_desktop_status
from serein.doctor.checks import run_checks
from serein.hardware.capabilities import build_capabilities
from serein.hardware.doctor import run_hardware_checks
from serein.hardware.planner import VALID_PROFILES, build_hardware_plan
from serein.hardware.probe import probe_hardware
from serein.profiles.models import ProfileManifest

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
