"""Explicit Layer-B closure gate for the Installer subsystem (S7.1
Section 52).

Mirrors ``serein.distribution.closure.enforce_layer_b_closure`` -
closure is never inferred merely from "the workflow's steps all ran";
this is the one explicit, fail-closed check that reads assembled
:class:`~serein.installer.models.InstallerLayerBEvidence` and raises
:class:`ClosureError` listing every failing reason unless ALL required
conditions hold simultaneously. The central S7.1 invariant - a target
disk may be destroyed intentionally, but every non-target disk must
remain byte-identical - is checked here as
``protected_disk_hash_unchanged`` alongside every other closure
requirement, never on its own as a partial proof.
"""

from __future__ import annotations

from serein.installer.models import InstallerLayerBEvidence


class ClosureError(ValueError):
    """Raised when Installer Layer-B evidence does not meet every
    closure requirement - the caller must treat this as a failed run,
    never a warning."""


def enforce_installer_layer_b_closure(
    evidence: InstallerLayerBEvidence, expected_source_commit: str
) -> None:
    """Raise :class:`ClosureError` with every failing reason listed
    unless ALL of the following hold (Section 52):

    - ``source_commit`` matches the expected exact HEAD
    - the installer backend was available
    - a target was explicitly selected AND re-validated immediately
      before execution
    - the install plan was valid AND every destructive operation was
      proven to belong to the target
    - the protected disk's hash is proven unchanged (never inferred)
      and its modification count is exactly 0
    - the target disk's hash actually changed (an install that touches
      nothing is not a real install)
    - the target has its own ESP and root filesystem
    - the protected disk's ESP is unchanged
    - the real installer run passed
    - the install media was removed before the installed-system boot
    - the installed system actually booted, in UEFI mode, with a real
      non-empty boot marker
    - Serein core is present on the installed system
    - first-boot provisioning is still "pending" - S7.1 must not have
      performed S7.2 work
    - production never defaults to autoinstall
    - no physical host disk was ever passed through
    """
    failures: list[str] = []

    if evidence.source_commit != expected_source_commit:
        failures.append(
            f"source_commit {evidence.source_commit!r} != expected {expected_source_commit!r}"
        )
    if not evidence.installer_backend_available:
        failures.append("installer_backend_available is not true")
    if not evidence.target_explicit:
        failures.append("target_explicit is not true")
    if not evidence.target_identity_revalidated:
        failures.append("target_identity_revalidated is not true")
    if not evidence.plan_valid:
        failures.append("plan_valid is not true")
    if not evidence.all_destructive_ops_on_target:
        failures.append("all_destructive_ops_on_target is not true")

    if evidence.protected_disk_modification_count != 0:
        failures.append(
            "protected_disk_modification_count="
            f"{evidence.protected_disk_modification_count} (require 0)"
        )
    if not evidence.protected_disk_hash_unchanged:
        failures.append("protected_disk_hash_unchanged is not true")
    if not evidence.target_disk_changed:
        failures.append("target_disk_changed is not true")

    if not evidence.target_esp_present:
        failures.append("target_esp_present is not true")
    if not evidence.target_root_present:
        failures.append("target_root_present is not true")
    if not evidence.protected_esp_unchanged:
        failures.append("protected_esp_unchanged is not true")

    if evidence.installation_status != "pass":
        failures.append(f"installation_status={evidence.installation_status!r} (require 'pass')")
    if not evidence.install_media_removed_for_boot:
        failures.append("install_media_removed_for_boot is not true")

    if evidence.installed_boot_status != "pass":
        failures.append(
            f"installed_boot_status={evidence.installed_boot_status!r} (require 'pass')"
        )
    if evidence.installed_boot_mode != "uefi":
        failures.append(f"installed_boot_mode={evidence.installed_boot_mode!r} (require 'uefi')")
    if not evidence.installed_boot_marker:
        failures.append("installed_boot_marker is empty - no real userspace evidence")
    if evidence.install_media_attached_during_installed_boot:
        failures.append("install_media_attached_during_installed_boot is true")

    if not evidence.serein_core_present:
        failures.append("serein_core_present is not true")
    if evidence.firstboot_provisioning != "pending":
        failures.append(
            f"firstboot_provisioning={evidence.firstboot_provisioning!r} (require 'pending')"
        )

    if evidence.autoinstall_production_default:
        failures.append("autoinstall_production_default is true")
    if evidence.physical_disk_passthrough:
        failures.append("physical_disk_passthrough is true")
    if not evidence.target_disk_attached:
        failures.append("target_disk_attached is not true")

    if failures:
        raise ClosureError(
            f"Installer Layer-B closure gate FAILED "
            f"({evidence.failure_stage or 'no stage recorded'}"
            f"{': ' + evidence.failure_reason if evidence.failure_reason else ''}):\n"
            + "\n".join(f"  - {reason}" for reason in failures)
        )
