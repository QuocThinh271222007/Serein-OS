"""Compact Layer-B evidence assembly (S7.0R Corrective A, Section 8-9;
partial/failure-tolerant model added by S7.0RM Corrective B).

Rather than uploading the ~6 GB ISO itself as a CI artifact, a Layer-B
run uploads this one small, machine-readable JSON file plus the build
manifests/sha256 sidecars already produced by
:mod:`serein.distribution.manifest`. Never includes a username,
hostname, home directory, or token - only the fields
``schemas/distribution-layer-b-evidence.schema.json`` declares.

**Every field except ``source_commit`` must be constructible even when
an early stage failed or never ran** (S7.0RM Corrective B - a real run
failed at the disk-space preflight, before any base download, and the
evidence-assembly step then crashed on a missing production manifest
file it assumed would exist). ``source_commit`` is known from the very
first workflow step (the exact-head checkout), before anything else
happens, so it is the only field this module ever requires as a plain
argument rather than an optional stage result.

**Schema v3 (S7.0RM5 Corrective B)** adds ``qa_transition`` - a real
Layer-B run reached, for the first time, a state where the production
ISO fully built and passed strict inspection but the in-place QA
transition then failed (a real ``PermissionError`` patching the
extracted GRUB config). The prior schema had no way to express that
without either lying that production had failed (it had not) or
lying that the QA build had failed (it never ran). ``qa_transition``
sits between ``production_inspection`` and ``qa_build`` in the real
pipeline order: "not_performed" before it is attempted (e.g. when
production itself failed), "pass" once
:func:`serein.distribution.qa_boot.transition_to_qa_in_place` returns
successfully, "fail" if it raises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DISTRIBUTION_LAYER_B_EVIDENCE_SCHEMA_VERSION = 3

#: Valid values for every stage-result field below - "not_performed" is
#: the honest default for a stage that never ran, never a guessed
#: "fail" or a fabricated "pass".
_STAGE_STATUSES = ("pass", "fail", "not_performed")


@dataclass(frozen=True)
class LayerBEvidence:
    source_commit: str
    failure_stage: str | None = None
    failure_reason: str | None = None

    base_filename: str | None = None
    base_sha256_expected: str | None = None
    base_sha256_actual: str | None = None
    base_verified: bool = False

    production_iso_filename: str | None = None
    production_iso_sha256: str | None = None
    production_build: str = "not_performed"
    production_inspection: str = "not_performed"

    qa_transition: str = "not_performed"

    qa_iso_filename: str | None = None
    qa_iso_sha256: str | None = None
    qa_build: str = "not_performed"
    qa_inspection: str = "not_performed"

    qemu_boot: str = "not_performed"
    qemu_boot_mode: str | None = None
    ovmf_firmware: str | None = None
    boot_marker: str | None = None

    target_disk_attached: bool = False
    autoinstall_enabled: bool = False
    schema_version: int = DISTRIBUTION_LAYER_B_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        stage_fields = (
            "production_build", "production_inspection",
            "qa_transition", "qa_build", "qa_inspection", "qemu_boot",
        )
        for field_name in stage_fields:
            value = getattr(self, field_name)
            if value not in _STAGE_STATUSES:
                raise ValueError(f"{field_name}={value!r} must be one of {_STAGE_STATUSES}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "base_filename": self.base_filename,
            "base_sha256_expected": self.base_sha256_expected,
            "base_sha256_actual": self.base_sha256_actual,
            "base_verified": self.base_verified,
            "production_iso_filename": self.production_iso_filename,
            "production_iso_sha256": self.production_iso_sha256,
            "production_build": self.production_build,
            "production_inspection": self.production_inspection,
            "qa_transition": self.qa_transition,
            "qa_iso_filename": self.qa_iso_filename,
            "qa_iso_sha256": self.qa_iso_sha256,
            "qa_build": self.qa_build,
            "qa_inspection": self.qa_inspection,
            "qemu_boot": self.qemu_boot,
            "qemu_boot_mode": self.qemu_boot_mode,
            "ovmf_firmware": self.ovmf_firmware,
            "boot_marker": self.boot_marker,
            "target_disk_attached": self.target_disk_attached,
            "autoinstall_enabled": self.autoinstall_enabled,
        }


def assemble_layer_b_evidence(
    source_commit: str,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    base_filename: str | None = None,
    base_sha256_expected: str | None = None,
    base_sha256_actual: str | None = None,
    production_iso_filename: str | None = None,
    production_iso_sha256: str | None = None,
    production_build: str = "not_performed",
    production_inspection: str = "not_performed",
    qa_transition: str = "not_performed",
    qa_iso_filename: str | None = None,
    qa_iso_sha256: str | None = None,
    qa_build: str = "not_performed",
    qa_inspection: str = "not_performed",
    qemu_boot: str = "not_performed",
    qemu_boot_mode: str | None = None,
    ovmf_firmware: str | None = None,
    boot_marker: str | None = None,
) -> LayerBEvidence:
    """Pure assembly - takes already-computed values, never re-runs
    anything and never assumes any file exists. Every stage argument
    defaults to "never happened" (``None``/``"not_performed"``) so a
    caller can build valid evidence after a failure at any point in the
    pipeline, including before the base image was ever downloaded.
    ``base_verified`` is derived, not passed in, so it can never
    silently disagree with the two hashes it is derived from - it is
    only ever true when both hashes are present and equal.
    """
    base_verified = (
        base_sha256_expected is not None
        and base_sha256_actual is not None
        and base_sha256_expected == base_sha256_actual
    )
    return LayerBEvidence(
        source_commit=source_commit,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        base_filename=base_filename,
        base_sha256_expected=base_sha256_expected,
        base_sha256_actual=base_sha256_actual,
        base_verified=base_verified,
        production_iso_filename=production_iso_filename,
        production_iso_sha256=production_iso_sha256,
        production_build=production_build,
        production_inspection=production_inspection,
        qa_transition=qa_transition,
        qa_iso_filename=qa_iso_filename,
        qa_iso_sha256=qa_iso_sha256,
        qa_build=qa_build,
        qa_inspection=qa_inspection,
        qemu_boot=qemu_boot,
        qemu_boot_mode=qemu_boot_mode,
        ovmf_firmware=ovmf_firmware,
        boot_marker=boot_marker,
        target_disk_attached=False,
        autoinstall_enabled=False,
    )


def write_layer_b_evidence(evidence: LayerBEvidence, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def load_layer_b_evidence(path: Path) -> LayerBEvidence:
    data = json.loads(path.read_text(encoding="utf-8"))
    return LayerBEvidence(
        source_commit=data["source_commit"],
        failure_stage=data.get("failure_stage"),
        failure_reason=data.get("failure_reason"),
        base_filename=data.get("base_filename"),
        base_sha256_expected=data.get("base_sha256_expected"),
        base_sha256_actual=data.get("base_sha256_actual"),
        base_verified=bool(data.get("base_verified", False)),
        production_iso_filename=data.get("production_iso_filename"),
        production_iso_sha256=data.get("production_iso_sha256"),
        production_build=data.get("production_build", "not_performed"),
        production_inspection=data.get("production_inspection", "not_performed"),
        qa_transition=data.get("qa_transition", "not_performed"),
        qa_iso_filename=data.get("qa_iso_filename"),
        qa_iso_sha256=data.get("qa_iso_sha256"),
        qa_build=data.get("qa_build", "not_performed"),
        qa_inspection=data.get("qa_inspection", "not_performed"),
        qemu_boot=data.get("qemu_boot", "not_performed"),
        qemu_boot_mode=data.get("qemu_boot_mode"),
        ovmf_firmware=data.get("ovmf_firmware"),
        boot_marker=data.get("boot_marker"),
        target_disk_attached=bool(data.get("target_disk_attached", False)),
        autoinstall_enabled=bool(data.get("autoinstall_enabled", False)),
        schema_version=data.get("schema_version", DISTRIBUTION_LAYER_B_EVIDENCE_SCHEMA_VERSION),
    )
