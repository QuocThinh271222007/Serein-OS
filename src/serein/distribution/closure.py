"""Explicit Layer-B closure gate (S7.0RM Corrective G).

Closure is never inferred merely from "the workflow's steps all ran" -
a real run can produce evidence for a partial/failed sequence and the
job could still exit 0 if nothing explicitly checks the evidence
afterward. ``enforce_layer_b_closure`` is that one explicit,
fail-closed check: it reads the assembled
:class:`~serein.distribution.evidence.LayerBEvidence` and raises
:class:`ClosureError` unless every required condition holds. The CLI
wrapper (``python -m serein.distribution closure-gate``) exits non-zero
on failure - the workflow's final step calls it with
``if: always()`` so a real defect always fails the job, evidence
collection notwithstanding (Section 43: "failure evidence + failed
workflow" is the desired, not the forbidden, outcome).
"""

from __future__ import annotations

from serein.distribution.evidence import LayerBEvidence


class ClosureError(ValueError):
    """Raised when Layer-B evidence does not meet every closure
    requirement - the caller must treat this as a failed run, never a
    warning."""


def enforce_layer_b_closure(evidence: LayerBEvidence, expected_source_commit: str) -> None:
    """Raise :class:`ClosureError` with every failing reason listed
    unless ALL of the following hold (Section 41):

    - ``source_commit`` matches the expected PR head exactly
    - ``base_verified`` is true
    - ``production_build``/``production_inspection`` are both "pass"
    - ``qa_transition`` is "pass" (S7.0RM5 Corrective B: a production
      pass alone must never satisfy closure - a real run proved
      production can fully succeed while the subsequent in-place QA
      transition still fails)
    - ``qa_build``/``qa_inspection`` are both "pass"
    - ``qemu_boot`` is "pass" and ``qemu_boot_mode`` is "uefi"
    - ``boot_marker`` is non-empty
    - ``target_disk_attached``/``autoinstall_enabled`` are both false
      (structural invariants - true unconditionally by construction,
      checked anyway so a future regression is caught here too)
    """
    failures: list[str] = []

    if evidence.source_commit != expected_source_commit:
        failures.append(
            f"source_commit {evidence.source_commit!r} != expected {expected_source_commit!r}"
        )
    if not evidence.base_verified:
        failures.append("base_verified is not true")
    if evidence.production_build != "pass":
        failures.append(f"production_build={evidence.production_build!r} (require 'pass')")
    if evidence.production_inspection != "pass":
        failures.append(
            f"production_inspection={evidence.production_inspection!r} (require 'pass')"
        )
    if evidence.qa_transition != "pass":
        failures.append(f"qa_transition={evidence.qa_transition!r} (require 'pass')")
    if evidence.qa_build != "pass":
        failures.append(f"qa_build={evidence.qa_build!r} (require 'pass')")
    if evidence.qa_inspection != "pass":
        failures.append(f"qa_inspection={evidence.qa_inspection!r} (require 'pass')")
    if evidence.qemu_boot != "pass":
        failures.append(f"qemu_boot={evidence.qemu_boot!r} (require 'pass')")
    if evidence.qemu_boot_mode != "uefi":
        failures.append(f"qemu_boot_mode={evidence.qemu_boot_mode!r} (require 'uefi')")
    if not evidence.boot_marker:
        failures.append("boot_marker is empty - no real userspace evidence")
    if evidence.target_disk_attached:
        failures.append("target_disk_attached is true")
    if evidence.autoinstall_enabled:
        failures.append("autoinstall_enabled is true")

    if failures:
        raise ClosureError(
            f"Layer-B closure gate FAILED ({evidence.failure_stage or 'no stage recorded'}"
            f"{': ' + evidence.failure_reason if evidence.failure_reason else ''}):\n"
            + "\n".join(f"  - {reason}" for reason in failures)
        )
