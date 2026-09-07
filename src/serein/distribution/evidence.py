"""Compact Layer-B evidence assembly (S7.0R Corrective A, Section 8-9).

Rather than uploading the ~6 GB ISO itself as a CI artifact, a Layer-B
run uploads this one small, machine-readable JSON file plus the build
manifests/sha256 sidecars already produced by
:mod:`serein.distribution.manifest`. Never includes a username,
hostname, home directory, or token - only the fields
``schemas/distribution-layer-b-evidence.schema.json`` declares.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DISTRIBUTION_LAYER_B_EVIDENCE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LayerBEvidence:
    source_commit: str
    base_filename: str
    base_sha256_expected: str
    base_sha256_actual: str
    base_verified: bool

    production_iso_filename: str
    production_iso_sha256: str
    production_iso_inspection: str  # "pass" | "fail" | "not_performed"

    qa_boot_iso_filename: str | None
    qa_boot_iso_sha256: str | None
    qemu_boot: str  # "pass" | "fail" | "not_performed"
    qemu_boot_mode: str | None
    boot_marker: str | None

    target_disk_attached: bool = False
    autoinstall_enabled: bool = False
    schema_version: int = DISTRIBUTION_LAYER_B_EVIDENCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "base_filename": self.base_filename,
            "base_sha256_expected": self.base_sha256_expected,
            "base_sha256_actual": self.base_sha256_actual,
            "base_verified": self.base_verified,
            "production_iso_filename": self.production_iso_filename,
            "production_iso_sha256": self.production_iso_sha256,
            "production_iso_inspection": self.production_iso_inspection,
            "qa_boot_iso_filename": self.qa_boot_iso_filename,
            "qa_boot_iso_sha256": self.qa_boot_iso_sha256,
            "qemu_boot": self.qemu_boot,
            "qemu_boot_mode": self.qemu_boot_mode,
            "boot_marker": self.boot_marker,
            "target_disk_attached": self.target_disk_attached,
            "autoinstall_enabled": self.autoinstall_enabled,
        }


def assemble_layer_b_evidence(
    source_commit: str,
    base_filename: str,
    base_sha256_expected: str,
    base_sha256_actual: str,
    production_iso_filename: str,
    production_iso_sha256: str,
    production_inspection_status: str = "not_performed",
    qa_boot_iso_filename: str | None = None,
    qa_boot_iso_sha256: str | None = None,
    qemu_boot: str = "not_performed",
    qemu_boot_mode: str | None = None,
    boot_marker: str | None = None,
) -> LayerBEvidence:
    """Pure assembly - takes already-computed values, never re-runs
    anything and never reaches into a :class:`~serein.distribution.build.BuildResult`
    or manifest object itself, so this stays trivially callable both
    from the real pipeline (after parsing its own manifests) and from
    a CLI/test that only has plain strings on hand. ``base_verified``
    is derived, not passed in, so it can never silently disagree with
    the two hashes it is derived from."""
    return LayerBEvidence(
        source_commit=source_commit,
        base_filename=base_filename,
        base_sha256_expected=base_sha256_expected,
        base_sha256_actual=base_sha256_actual,
        base_verified=base_sha256_expected == base_sha256_actual,
        production_iso_filename=production_iso_filename,
        production_iso_sha256=production_iso_sha256,
        production_iso_inspection=production_inspection_status,
        qa_boot_iso_filename=qa_boot_iso_filename,
        qa_boot_iso_sha256=qa_boot_iso_sha256,
        qemu_boot=qemu_boot,
        qemu_boot_mode=qemu_boot_mode,
        boot_marker=boot_marker,
        target_disk_attached=False,
        autoinstall_enabled=False,
    )


def write_layer_b_evidence(evidence: LayerBEvidence, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path
