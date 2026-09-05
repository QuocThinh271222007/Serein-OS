"""Schema contract tests: schema files are valid, and real output from the
tool validates against them."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from serein.doctor.checks import run_checks
from serein.hardware.probe import probe_hardware
from serein.profiles.models import ProfileManifest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ["hardware-report.schema.json", "doctor-report.schema.json", "profile.schema.json"],
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


def test_core_profile_manifest_validates_against_schema() -> None:
    schema = _load_schema("profile.schema.json")
    data = json.loads((REPO_ROOT / "profiles" / "core" / "core.profile.json").read_text())
    jsonschema.validate(instance=data, schema=schema)
    # Also confirm it round-trips through our own model shape.
    manifest = ProfileManifest.from_dict(data)
    jsonschema.validate(instance=manifest.to_dict(), schema=schema)
