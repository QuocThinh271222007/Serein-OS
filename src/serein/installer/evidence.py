"""Compact Layer-B evidence assembly for the Installer subsystem (S7.1
Section 38).

Mirrors ``serein.distribution.evidence`` exactly: every field except
``source_commit`` must be constructible even when an early stage failed
or never ran (a real S7.0 run proved this matters - see
``docs/distribution/known-limitations.md``'s Run 1/2 history). Every
derived boolean (``target_disk_changed``, ``protected_disk_hash_unchanged``,
``protected_disk_modification_count``) is computed HERE, from real hash
pairs, so it can never silently disagree with the hashes it is derived
from - a caller cannot directly assert ``protected_disk_hash_unchanged=True``
without the matching before/after hashes actually agreeing.
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.installer.models import (
    INSTALLER_LAYER_B_EVIDENCE_SCHEMA_VERSION,
    InstallerLayerBEvidence,
    TargetDiskIdentity,
)


def _target_changed(before: str | None, after: str | None) -> bool:
    # Only ever True when BOTH hashes are real and disagree - never
    # inferred from one missing hash (Section 45).
    return before is not None and after is not None and before != after


def _protected_modification_count(before: tuple[str, ...], after: tuple[str, ...]) -> int:
    if len(before) != len(after):
        # A protected disk appearing/disappearing between the two
        # hashing passes is itself evidence of change - conservative,
        # never silently ignored.
        return max(len(before), len(after))
    return sum(1 for b, a in zip(before, after, strict=True) if b != a)


def _protected_hash_unchanged(before: tuple[str, ...], after: tuple[str, ...]) -> bool:
    # Vacuously "unchanged" (empty before/after) must NEVER read as
    # true protection evidence (Section 44 - "do not infer this merely
    # from installer logs... hash the disk image bytes").
    return bool(before) and before == after


def assemble_installer_layer_b_evidence(
    source_commit: str,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    installer_backend: str | None = None,
    installer_backend_version: str | None = None,
    installer_backend_available: bool = False,
    target_explicit: bool = False,
    target_identity: TargetDiskIdentity | None = None,
    target_identity_revalidated: bool = False,
    protected_disk_identities: tuple[TargetDiskIdentity, ...] = (),
    plan_valid: bool = False,
    all_destructive_ops_on_target: bool = False,
    target_disk_before_sha256: str | None = None,
    target_disk_after_sha256: str | None = None,
    protected_disk_before_sha256: tuple[str, ...] = (),
    protected_disk_after_sha256: tuple[str, ...] = (),
    target_esp_present: bool = False,
    target_root_present: bool = False,
    protected_esp_unchanged: bool = False,
    installation_status: str = "not_performed",
    install_media_removed_for_boot: bool = False,
    installed_boot_status: str = "not_performed",
    installed_boot_mode: str | None = None,
    installed_boot_marker: str | None = None,
    install_media_attached_during_installed_boot: bool = True,
    serein_core_present: bool = False,
    firstboot_provisioning: str = "unknown",
    autoinstall_mode: str = "qa_only",
    target_disk_attached: bool = False,
) -> InstallerLayerBEvidence:
    """Pure assembly - takes already-computed values, never re-runs
    anything and never assumes any file/disk exists. Every stage
    argument defaults to "never happened" so a caller can build valid
    evidence after a failure at any point in the pipeline, including
    before a target was ever selected.

    ``target_disk_attached`` is a RUNTIME fact (S7.1R Corrective B/
    Section 17), never a structural invariant like
    ``physical_disk_passthrough`` - a real run recorded it as
    unconditionally ``True`` even when the pipeline failed at disk
    preflight, before any fixture disk was ever created. It defaults to
    ``False`` and must only ever be set ``True`` by a caller that has
    observed the real fixture-disk topology actually exists (never
    merely that the workflow source code declares a target serial)."""
    return InstallerLayerBEvidence(
        source_commit=source_commit,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        installer_backend=installer_backend,
        installer_backend_version=installer_backend_version,
        installer_backend_available=installer_backend_available,
        target_explicit=target_explicit,
        target_identity=target_identity,
        target_identity_revalidated=target_identity_revalidated,
        protected_disk_identities=protected_disk_identities,
        plan_valid=plan_valid,
        all_destructive_ops_on_target=all_destructive_ops_on_target,
        target_disk_before_sha256=target_disk_before_sha256,
        target_disk_after_sha256=target_disk_after_sha256,
        target_disk_changed=_target_changed(target_disk_before_sha256, target_disk_after_sha256),
        protected_disk_before_sha256=protected_disk_before_sha256,
        protected_disk_after_sha256=protected_disk_after_sha256,
        protected_disk_modification_count=_protected_modification_count(
            protected_disk_before_sha256, protected_disk_after_sha256
        ),
        protected_disk_hash_unchanged=_protected_hash_unchanged(
            protected_disk_before_sha256, protected_disk_after_sha256
        ),
        target_esp_present=target_esp_present,
        target_root_present=target_root_present,
        protected_esp_unchanged=protected_esp_unchanged,
        installation_status=installation_status,
        install_media_removed_for_boot=install_media_removed_for_boot,
        installed_boot_status=installed_boot_status,
        installed_boot_mode=installed_boot_mode,
        installed_boot_marker=installed_boot_marker,
        install_media_attached_during_installed_boot=(
            install_media_attached_during_installed_boot
        ),
        serein_core_present=serein_core_present,
        firstboot_provisioning=firstboot_provisioning,
        autoinstall_mode=autoinstall_mode,
        target_disk_attached=target_disk_attached,
        # Structural invariants - never caller-supplied, always the
        # safe constant (Section 49-50: no physical disk passthrough,
        # ever, in Layer-B CI; production media never defaults to
        # autoinstall). Unlike target_disk_attached above, these two
        # really are true unconditionally by construction - the code
        # path that could set them otherwise does not exist.
        autoinstall_production_default=False,
        physical_disk_passthrough=False,
    )


def write_installer_layer_b_evidence(evidence: InstallerLayerBEvidence, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _identity_from_dict(data: dict | None) -> TargetDiskIdentity | None:
    if data is None:
        return None
    return TargetDiskIdentity(
        serial=data.get("serial"),
        wwn=data.get("wwn"),
        id_path=data.get("id_path"),
        model=data.get("model"),
        size_bytes=data.get("size_bytes"),
        observed_device_path=data.get("observed_device_path"),
    )


def load_installer_layer_b_evidence(path: Path) -> InstallerLayerBEvidence:
    data = json.loads(path.read_text(encoding="utf-8"))
    return InstallerLayerBEvidence(
        source_commit=data["source_commit"],
        failure_stage=data.get("failure_stage"),
        failure_reason=data.get("failure_reason"),
        installer_backend=data.get("installer_backend"),
        installer_backend_version=data.get("installer_backend_version"),
        installer_backend_available=bool(data.get("installer_backend_available", False)),
        target_explicit=bool(data.get("target_explicit", False)),
        target_identity=_identity_from_dict(data.get("target_identity")),
        target_identity_revalidated=bool(data.get("target_identity_revalidated", False)),
        protected_disk_identities=tuple(
            i for i in (
                _identity_from_dict(d) for d in data.get("protected_disk_identities", [])
            ) if i is not None
        ),
        plan_valid=bool(data.get("plan_valid", False)),
        all_destructive_ops_on_target=bool(data.get("all_destructive_ops_on_target", False)),
        target_disk_before_sha256=data.get("target_disk_before_sha256"),
        target_disk_after_sha256=data.get("target_disk_after_sha256"),
        target_disk_changed=bool(data.get("target_disk_changed", False)),
        protected_disk_before_sha256=tuple(data.get("protected_disk_before_sha256", [])),
        protected_disk_after_sha256=tuple(data.get("protected_disk_after_sha256", [])),
        protected_disk_modification_count=int(data.get("protected_disk_modification_count", 0)),
        protected_disk_hash_unchanged=bool(data.get("protected_disk_hash_unchanged", False)),
        target_esp_present=bool(data.get("target_esp_present", False)),
        target_root_present=bool(data.get("target_root_present", False)),
        protected_esp_unchanged=bool(data.get("protected_esp_unchanged", False)),
        installation_status=data.get("installation_status", "not_performed"),
        install_media_removed_for_boot=bool(data.get("install_media_removed_for_boot", False)),
        installed_boot_status=data.get("installed_boot_status", "not_performed"),
        installed_boot_mode=data.get("installed_boot_mode"),
        installed_boot_marker=data.get("installed_boot_marker"),
        install_media_attached_during_installed_boot=bool(
            data.get("install_media_attached_during_installed_boot", True)
        ),
        serein_core_present=bool(data.get("serein_core_present", False)),
        firstboot_provisioning=data.get("firstboot_provisioning", "unknown"),
        autoinstall_mode=data.get("autoinstall_mode", "qa_only"),
        autoinstall_production_default=bool(data.get("autoinstall_production_default", False)),
        target_disk_attached=bool(data.get("target_disk_attached", False)),
        physical_disk_passthrough=bool(data.get("physical_disk_passthrough", False)),
        schema_version=int(
            data.get("schema_version", INSTALLER_LAYER_B_EVIDENCE_SCHEMA_VERSION)
        ),
    )
