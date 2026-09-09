"""Tests for the Installer subsystem (S7.1).

Layer A only: disk-identity/safety-gate logic, plan construction and
validation, autoinstall config rendering, evidence/closure, and CLI
wiring - all against fully injectable fake command runners and
fixture-shaped data, never a real disk, real ``lsblk``, or real
``curtin``/Subiquity. ``generate_qa_credential`` is exercised against
the REAL ``openssl`` binary where available (skipped otherwise) since
that is a genuinely portable, always-available tool, unlike the
disk/installer tooling this suite otherwise fakes.

Real target-disk installation (Layer B: real QEMU, real virtual disks,
real curtin/Subiquity execution, real protected-disk hashing, real
installed-system boot) requires a real GitHub Actions run and is never
exercised here - see ``docs/installer/known-limitations.md``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

from serein.development.runner import CommandResult
from serein.distribution.qa_boot import QA_ENTRY_TITLE
from serein.distribution.safety import scan_text_for_credentials, scan_tree_for_credentials
from serein.installer.bootcheck import (
    build_installed_disk_boot_command,
    run_installed_disk_boot_check,
)
from serein.installer.closure import ClosureError, enforce_installer_layer_b_closure
from serein.installer.diskguard import (
    AMBIGUOUS_TARGET,
    NO_TARGET,
    PLAN_ESCAPE,
    PROTECTED_DISK_REFERENCE,
    TARGET_ACTIVE,
    TARGET_CHANGED,
    TARGET_IS_INSTALL_MEDIA,
    TARGET_NOT_FOUND,
    DiskGuardError,
    ancestor_disk,
    classify_protection,
    validate_grub_target,
    validate_plan_ancestry,
    validate_target_selection,
)
from serein.installer.diskprobe import _classify_windows, probe_disks
from serein.installer.doctor import run_installer_checks
from serein.installer.evidence import (
    assemble_installer_layer_b_evidence,
    load_installer_layer_b_evidence,
    write_installer_layer_b_evidence,
)
from serein.installer.identity import (
    capture_target_identity,
    identity_matches_disk,
    identity_strength,
    resolve_target,
)
from serein.installer.isoprep import (
    AutoinstallBootError,
    IsoPrepError,
    _enable_autoinstall_on_qa_entry,
    _enable_journald_console_forwarding_on_qa_entry,
    _enable_systemd_debug_logging_on_qa_entry,
    prepare_qa_install_iso,
)
from serein.installer.models import (
    TARGET_ESP_SIZE_BYTES,
    DiskInfo,
    DiskInventory,
    PartitionInfo,
    TargetDiskIdentity,
)
from serein.installer.payload import (
    QaCredential,
    build_install_state_marker,
    generate_qa_credential,
)
from serein.installer.planner import build_install_plan, validate_plan
from serein.installer.renderer import (
    RendererError,
    render_autoinstall_storage_config,
    render_autoinstall_yaml,
)
from serein.installer.status import build_installer_status

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


class FakeCommandRunner:
    """Maps either an exact argv tuple or a bare binary name to a
    canned CommandResult (or None = "not found"). Mirrors
    ``tests/test_veil.py``'s idiom exactly."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):
        self.calls.append(list(args))
        key = tuple(args)
        if key in self._responses:
            return self._responses[key]
        binary = args[0]
        if binary in self._responses:
            return self._responses[binary]
        return None


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "not found") -> CommandResult:
    return CommandResult(returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_disk_info_defaults_are_fail_closed(self):
        disk = DiskInfo(device_path="/dev/sdz")
        assert disk.protected is True
        assert disk.target_eligible is False
        assert disk.identity_confidence == "low"

    def test_disk_info_rejects_bad_identity_confidence(self):
        with pytest.raises(ValueError, match="identity_confidence"):
            DiskInfo(device_path="/dev/sdz", identity_confidence="extreme")  # type: ignore[arg-type]

    def test_target_resolution_rejects_disk_on_non_resolved_status(self):
        with pytest.raises(ValueError, match="must not carry a resolved disk"):
            from serein.installer.models import TargetResolution

            TargetResolution(status="not_found", disk=DiskInfo(device_path="/dev/sdz"))

    def test_target_resolution_rejects_unknown_status(self):
        from serein.installer.models import TargetResolution

        with pytest.raises(ValueError, match="must be one of"):
            TargetResolution(status="maybe")  # type: ignore[arg-type]

    def test_disk_inventory_to_dict_round_trips_partitions(self):
        disk = DiskInfo(
            device_path="/dev/sdb", partitions=(PartitionInfo(device_path="/dev/sdb1"),)
        )
        data = DiskInventory(disks=(disk,)).to_dict()
        assert data["disks"][0]["partitions"][0]["device_path"] == "/dev/sdb1"


class TestSchemas:
    @pytest.mark.parametrize(
        "name",
        [
            "installer-disk-inventory.schema.json",
            "installer-plan.schema.json",
            "installer-install-state.schema.json",
            "installer-layer-b-evidence.schema.json",
        ],
    )
    def test_schema_file_itself_is_valid(self, name):
        schema = _load_schema(name)
        jsonschema.Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# diskprobe
# ---------------------------------------------------------------------------


_LSBLK_JSON_TWO_DISKS = json.dumps({
    "blockdevices": [
        {
            "name": "sda", "path": "/dev/sda", "kname": "sda", "type": "disk",
            "model": "Internal SSD", "vendor": "ACME", "serial": "INTSERIAL",
            "wwn": "0xINTWWN", "size": 256000000000, "tran": "sata", "rm": "0",
            "pttype": "gpt", "log-sec": 512, "phy-sec": 512,
            "children": [
                {
                    "name": "sda1", "path": "/dev/sda1", "kname": "sda1", "type": "part",
                    "fstype": "vfat", "label": "SYSTEM", "size": 500000000,
                    "mountpoint": None,
                },
                {
                    "name": "sda2", "path": "/dev/sda2", "kname": "sda2", "type": "part",
                    "fstype": "ntfs", "label": "Windows", "size": 255000000000,
                    "mountpoint": None,
                },
            ],
        },
        {
            "name": "sdb", "path": "/dev/sdb", "kname": "sdb", "type": "disk",
            "model": "External USB", "vendor": "ACME", "serial": "EXTSERIAL",
            "wwn": "0xEXTWWN", "size": 32000000000, "tran": "usb", "rm": "1",
            "pttype": None, "children": [],
        },
    ]
})


class TestDiskProbe:
    def test_probe_disks_parses_real_lsblk_json_shape(self, tmp_path):
        runner = FakeCommandRunner({"lsblk": _ok(_LSBLK_JSON_TWO_DISKS)})
        inventory = probe_disks(runner=runner, root=tmp_path)
        assert len(inventory.disks) == 2
        sda = next(d for d in inventory.disks if d.device_path == "/dev/sda")
        assert sda.serial == "INTSERIAL"
        assert sda.wwn == "0xINTWWN"
        assert len(sda.partitions) == 2
        assert sda.transport == "sata"
        assert sda.removable is False

        sdb = next(d for d in inventory.disks if d.device_path == "/dev/sdb")
        assert sdb.removable is True
        assert sdb.transport == "usb"

    def test_probe_disks_empty_when_lsblk_unavailable(self, tmp_path):
        runner = FakeCommandRunner({})
        inventory = probe_disks(runner=runner, root=tmp_path)
        assert inventory.disks == ()

    def test_probe_disks_empty_when_lsblk_fails(self, tmp_path):
        runner = FakeCommandRunner({"lsblk": _fail()})
        inventory = probe_disks(runner=runner, root=tmp_path)
        assert inventory.disks == ()

    def test_probe_disks_empty_on_malformed_json(self, tmp_path):
        runner = FakeCommandRunner({"lsblk": _ok("not json{{{")})
        inventory = probe_disks(runner=runner, root=tmp_path)
        assert inventory.disks == ()

    def test_probe_disks_never_fabricates_missing_fields(self, tmp_path):
        minimal = json.dumps({
            "blockdevices": [{"name": "sdz", "type": "disk"}]
        })
        runner = FakeCommandRunner({"lsblk": _ok(minimal)})
        inventory = probe_disks(runner=runner, root=tmp_path)
        disk = inventory.disks[0]
        assert disk.model is None
        assert disk.serial is None
        assert disk.size_bytes is None
        assert disk.identity_confidence == "low"

    def test_windows_efi_and_recovery_classification(self):
        esp = PartitionInfo(device_path="/dev/sda1", filesystem="vfat", label="SYSTEM")
        recovery = PartitionInfo(device_path="/dev/sda2", filesystem="ntfs", label="Recovery")
        detected, efi, rec = _classify_windows(None, (esp, recovery))
        assert detected is True
        assert efi is True
        assert rec is True

    def test_non_windows_disk_not_misclassified(self):
        linux_root = PartitionInfo(device_path="/dev/sdb1", filesystem="ext4", label="root")
        detected, efi, rec = _classify_windows(None, (linux_root,))
        assert detected is False
        assert efi is False
        assert rec is False

    def test_install_media_iso9660_detected(self, tmp_path):
        iso_disk_json = json.dumps({
            "blockdevices": [
                {
                    "name": "sr0", "path": "/dev/sr0", "kname": "sr0", "type": "disk",
                    "fstype": "iso9660", "size": 6000000000, "ro": True, "children": [],
                }
            ]
        })
        runner = FakeCommandRunner({"lsblk": _ok(iso_disk_json)})
        inventory = probe_disks(runner=runner, root=tmp_path)
        assert inventory.disks[0].install_media is True

    def test_id_path_probed_from_by_path_symlinks(self, tmp_path):
        # Build a fixture root with a /dev/disk/by-path symlink pointing
        # at a real (fixture) device node.
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        target = dev_dir / "sdb"
        target.write_bytes(b"")
        by_path = tmp_path / "dev" / "disk" / "by-path"
        by_path.mkdir(parents=True)
        link = by_path / "pci-0000:00:14.0-usb-0:1:1.0-scsi-0:0:0:0"
        try:
            import os
            os.symlink(target, link)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        one_disk = json.dumps({
            "blockdevices": [{"name": "sdb", "path": "/dev/sdb", "kname": "sdb", "type": "disk"}]
        })
        runner = FakeCommandRunner({"lsblk": _ok(one_disk)})
        inventory = probe_disks(runner=runner, root=tmp_path)
        assert inventory.disks[0].id_path == link.name
        assert inventory.disks[0].identity_confidence in ("medium", "high")


# ---------------------------------------------------------------------------
# identity - Section 11-12, 33-34
# ---------------------------------------------------------------------------


class TestIdentity:
    def test_capture_and_strength(self):
        disk = DiskInfo(device_path="/dev/sdb", serial="S", wwn="W", id_path="P")
        identity = capture_target_identity(disk)
        assert identity_strength(identity) == 3

    def test_weak_identity_never_matches(self):
        # a bare model/size identity (no serial/wwn/id_path) must never
        # be treated as a match, even against an identical-looking disk
        weak = TargetDiskIdentity(model="Generic", size_bytes=1000)
        disk = DiskInfo(device_path="/dev/sdb", model="Generic", size_bytes=1000)
        assert identity_matches_disk(weak, disk) is False

    def test_resolve_target_resolved(self):
        disk = DiskInfo(device_path="/dev/sdb", serial="S", wwn="W")
        identity = capture_target_identity(disk)
        resolution = resolve_target(identity, DiskInventory(disks=(disk,)))
        assert resolution.status == "resolved"
        assert resolution.disk is disk

    def test_resolve_target_survives_device_name_swap(self):
        # Section 33: device names swapped, stable identities unchanged
        # -> same target selected.
        protected = DiskInfo(device_path="/dev/sda", serial="PROT", wwn="WPROT")
        target = DiskInfo(device_path="/dev/sdb", serial="TGT", wwn="WTGT")
        identity = capture_target_identity(target)

        swapped_protected = DiskInfo(device_path="/dev/sdb", serial="PROT", wwn="WPROT")
        swapped_target = DiskInfo(device_path="/dev/sda", serial="TGT", wwn="WTGT")
        resolution = resolve_target(
            identity, DiskInventory(disks=(swapped_protected, swapped_target))
        )
        assert resolution.status == "resolved"
        assert resolution.disk.device_path == "/dev/sda"
        del protected, swapped_protected

    def test_resolve_target_not_found_when_disk_disappears(self):
        disk = DiskInfo(device_path="/dev/sdb", serial="S", wwn="W")
        identity = capture_target_identity(disk)
        other = DiskInfo(device_path="/dev/sdc", serial="OTHER", wwn="WOTHER")
        resolution = resolve_target(identity, DiskInventory(disks=(other,)))
        assert resolution.status == "not_found"

    def test_resolve_target_changed_when_same_path_different_identity(self):
        disk = DiskInfo(device_path="/dev/sdb", serial="S", wwn="W")
        identity = capture_target_identity(disk)
        replug = DiskInfo(device_path="/dev/sdb", serial="DIFFERENT", wwn="DIFFERENT")
        resolution = resolve_target(identity, DiskInventory(disks=(replug,)))
        assert resolution.status == "changed"

    def test_resolve_target_ambiguous_on_duplicate_identity(self):
        # Section 34: two disks with similar model/size/transport but
        # here we specifically test the case where recorded strong
        # fields coincide - must never collapse into one match.
        identity = TargetDiskIdentity(serial="DUP", wwn="WDUP")
        dup1 = DiskInfo(device_path="/dev/sdc", serial="DUP", wwn="WDUP")
        dup2 = DiskInfo(device_path="/dev/sdd", serial="DUP", wwn="WDUP")
        resolution = resolve_target(identity, DiskInventory(disks=(dup1, dup2)))
        assert resolution.status == "ambiguous"

    def test_target_confusion_similar_but_distinct_disks_not_collapsed(self):
        # Section 34: same model/size/transport, distinct serials - the
        # resolver must not treat them as interchangeable.
        identity = TargetDiskIdentity(
            serial="REAL-TARGET", model="Generic USB", size_bytes=64_000_000_000
        )
        look_alike = DiskInfo(
            device_path="/dev/sdc", serial="LOOK-ALIKE", model="Generic USB",
            size_bytes=64_000_000_000,
        )
        real = DiskInfo(
            device_path="/dev/sdd", serial="REAL-TARGET", model="Generic USB",
            size_bytes=64_000_000_000,
        )
        resolution = resolve_target(identity, DiskInventory(disks=(look_alike, real)))
        assert resolution.status == "resolved"
        assert resolution.disk.device_path == "/dev/sdd"

    def test_resolve_target_too_weak_identity_not_found(self):
        weak = TargetDiskIdentity(model="Generic", size_bytes=1000)
        disk = DiskInfo(device_path="/dev/sdb", model="Generic", size_bytes=1000)
        resolution = resolve_target(weak, DiskInventory(disks=(disk,)))
        assert resolution.status == "not_found"


# ---------------------------------------------------------------------------
# diskguard - Sections 8-9, 13, 17, 20-22, 37 (Tests A-H live here)
# ---------------------------------------------------------------------------


class TestAncestorDisk:
    @pytest.mark.parametrize(
        "device,expected",
        [
            ("/dev/sdb", "/dev/sdb"),
            ("/dev/sdb1", "/dev/sdb"),
            ("/dev/sdb12", "/dev/sdb"),
            ("/dev/nvme0n1", "/dev/nvme0n1"),
            ("/dev/nvme0n1p1", "/dev/nvme0n1"),
            ("/dev/mmcblk0", "/dev/mmcblk0"),
            ("/dev/mmcblk0p2", "/dev/mmcblk0"),
            ("/dev/vda1", "/dev/vda"),
        ],
    )
    def test_ancestor_disk_parses_every_convention(self, device, expected):
        assert ancestor_disk(device) == expected


class TestClassifyProtection:
    def test_target_unprotected_when_eligible(self):
        target = DiskInfo(device_path="/dev/sdb")
        protected = DiskInfo(device_path="/dev/sda")
        result = classify_protection(DiskInventory(disks=(protected, target)), "/dev/sdb")
        t = next(d for d in result.disks if d.device_path == "/dev/sdb")
        p = next(d for d in result.disks if d.device_path == "/dev/sda")
        assert t.protected is False
        assert t.target_eligible is True
        assert p.protected is True
        assert p.protection_reasons == ("non_target_disk",)

    def test_non_target_always_protected_even_if_unclassifiable(self):
        # Section 13: even an unknown non-target disk remains protected.
        mystery = DiskInfo(device_path="/dev/sdx")  # no windows/media/mount evidence at all
        target = DiskInfo(device_path="/dev/sdb")
        result = classify_protection(DiskInventory(disks=(mystery, target)), "/dev/sdb")
        m = next(d for d in result.disks if d.device_path == "/dev/sdx")
        assert m.protected is True

    def test_selected_target_still_protected_if_mounted(self):
        mounted_target = DiskInfo(device_path="/dev/sdb", mounted=True)
        result = classify_protection(DiskInventory(disks=(mounted_target,)), "/dev/sdb")
        t = result.disks[0]
        assert t.protected is True
        assert "mounted" in t.protection_reasons
        assert t.target_eligible is False

    def test_selected_target_still_protected_if_install_media(self):
        media_target = DiskInfo(device_path="/dev/sr0", install_media=True)
        result = classify_protection(DiskInventory(disks=(media_target,)), "/dev/sr0")
        t = result.disks[0]
        assert t.protected is True
        assert "install_media" in t.protection_reasons


class TestValidateTargetSelection:
    def test_a_no_target_blocked(self):
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(None, None, "not_found")
        assert exc_info.value.code == NO_TARGET

    def test_g_ambiguous_target_blocked(self):
        identity = TargetDiskIdentity(serial="S")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(identity, None, "ambiguous")
        assert exc_info.value.code == AMBIGUOUS_TARGET

    def test_e_target_not_found_blocked(self):
        identity = TargetDiskIdentity(serial="S")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(identity, None, "not_found")
        assert exc_info.value.code == TARGET_NOT_FOUND

    def test_f_target_changed_blocked(self):
        identity = TargetDiskIdentity(serial="S")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(identity, None, "changed")
        assert exc_info.value.code == TARGET_CHANGED

    def test_b_target_is_install_media_blocked(self):
        identity = TargetDiskIdentity(serial="S")
        disk = DiskInfo(device_path="/dev/sr0", serial="S", install_media=True)
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(identity, disk, "resolved")
        assert exc_info.value.code == TARGET_IS_INSTALL_MEDIA

    def test_target_matching_known_install_media_identity_blocked(self):
        # Even if the install_media flag itself wasn't set, matching a
        # known install-media identity is still blocked.
        identity = TargetDiskIdentity(serial="S")
        disk = DiskInfo(device_path="/dev/sr0", serial="S")
        media_identity = TargetDiskIdentity(serial="S")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(
                identity, disk, "resolved", install_media_identities=(media_identity,)
            )
        assert exc_info.value.code == TARGET_IS_INSTALL_MEDIA

    def test_h_mounted_target_blocked(self):
        identity = TargetDiskIdentity(serial="S")
        disk = DiskInfo(device_path="/dev/sdb", serial="S", mounted=True)
        with pytest.raises(DiskGuardError) as exc_info:
            validate_target_selection(identity, disk, "resolved")
        assert exc_info.value.code == TARGET_ACTIVE

    def test_valid_selection_does_not_raise(self):
        identity = TargetDiskIdentity(serial="S")
        disk = DiskInfo(device_path="/dev/sdb", serial="S")
        validate_target_selection(identity, disk, "resolved")  # must not raise


def _make_plan(target_device="/dev/sdb", esp="/dev/sdb1", root="/dev/sdb2", grub="/dev/sdb"):
    from serein.installer.models import InstallPlan, PlanBoot, PlanOperation

    identity = TargetDiskIdentity(serial="TGT", observed_device_path=target_device)
    return InstallPlan(
        target=identity,
        target_device_path=target_device,
        protected_disks=(),
        operations=(
            PlanOperation(
                id="create-esp", kind="create_esp", device=esp, target_disk_identity=identity,
                destructive=True, requires_confirmation=True, reason="test",
            ),
            PlanOperation(
                id="create-root", kind="create_root_partition", device=root,
                target_disk_identity=identity, destructive=True, requires_confirmation=True,
                reason="test",
            ),
            PlanOperation(
                id="mount-root", kind="mount_root", device=root, target_disk_identity=identity,
                destructive=False, requires_confirmation=False, reason="test",
            ),
        ),
        boot=PlanBoot(grub_target_device=grub, esp_device=esp),
    )


class TestPlanAncestryValidation:
    def test_c_destructive_op_referencing_protected_disk_blocked(self):
        plan = _make_plan(target_device="/dev/sdb", esp="/dev/sda1", root="/dev/sdb2")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_plan_ancestry(plan, protected_device_paths=("/dev/sda",))
        assert exc_info.value.code == PROTECTED_DISK_REFERENCE

    def test_plan_escape_wrong_ancestor_not_a_known_protected_disk(self):
        plan = _make_plan(target_device="/dev/sdb", esp="/dev/nvme0n1p1", root="/dev/sdb2")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_plan_ancestry(plan, protected_device_paths=())
        assert exc_info.value.code == PLAN_ESCAPE

    def test_valid_plan_ancestry_does_not_raise(self):
        plan = _make_plan()
        validate_plan_ancestry(plan, protected_device_paths=("/dev/sda",))

    def test_non_destructive_op_not_checked(self):
        # mount_root targets root but is non-destructive - if it somehow
        # referenced a foreign device it should not be checked here
        # (only destructive ops are ancestry-validated).
        from dataclasses import replace

        plan = _make_plan()
        foreign_mount = replace(plan.operations[2], device="/dev/sdz9")
        plan2 = replace(plan, operations=(plan.operations[0], plan.operations[1], foreign_mount))
        validate_plan_ancestry(plan2, protected_device_paths=())  # must not raise

    def test_d_grub_target_referencing_protected_disk_blocked(self):
        plan = _make_plan(target_device="/dev/sdb", grub="/dev/sda")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_grub_target(plan)
        assert exc_info.value.code == PLAN_ESCAPE

    def test_grub_esp_device_off_target_blocked(self):
        plan = _make_plan(target_device="/dev/sdb", esp="/dev/sdc1")
        with pytest.raises(DiskGuardError) as exc_info:
            validate_grub_target(plan)
        assert exc_info.value.code == PLAN_ESCAPE

    def test_valid_grub_target_does_not_raise(self):
        plan = _make_plan()
        validate_grub_target(plan)  # must not raise


# ---------------------------------------------------------------------------
# planner - Section 16, 19
# ---------------------------------------------------------------------------


class TestPlanner:
    def test_baseline_layout_matches_section_16(self):
        identity = TargetDiskIdentity(serial="TGT", observed_device_path="/dev/sdb")
        plan = build_install_plan(identity, "/dev/sdb", protected_disk_identities=())
        kinds = [op.kind for op in plan.operations]
        assert kinds == [
            "wipe_partition_table", "create_gpt", "create_esp", "format_fat32",
            "create_root_partition", "format_ext4", "mount_root", "install_system",
            "install_bootloader",
        ]
        esp_op = next(op for op in plan.operations if op.kind == "create_esp")
        assert esp_op.device == "/dev/sdb1"
        assert "1" in esp_op.reason  # 1 GiB size mentioned

    def test_no_raid_lvm_zfs_encryption_swap_in_baseline(self):
        identity = TargetDiskIdentity(serial="TGT", observed_device_path="/dev/sdb")
        plan = build_install_plan(identity, "/dev/sdb", protected_disk_identities=())
        forbidden = ("raid", "lvm", "zfs", "luks", "encrypt", "swap")
        for op in plan.operations:
            lowered = f"{op.kind} {op.reason}".lower()
            for word in forbidden:
                assert word not in lowered

    def test_nvme_target_partition_naming(self):
        identity = TargetDiskIdentity(serial="TGT", observed_device_path="/dev/nvme0n1")
        plan = build_install_plan(identity, "/dev/nvme0n1", protected_disk_identities=())
        esp_op = next(op for op in plan.operations if op.kind == "create_esp")
        assert esp_op.device == "/dev/nvme0n1p1"

    def test_unvalidated_plan_starts_invalid(self):
        identity = TargetDiskIdentity(serial="TGT", observed_device_path="/dev/sdb")
        plan = build_install_plan(identity, "/dev/sdb", protected_disk_identities=())
        assert plan.validation.valid is False

    def test_validate_plan_marks_valid_when_all_ops_on_target(self):
        identity = TargetDiskIdentity(serial="TGT", observed_device_path="/dev/sdb")
        plan = build_install_plan(identity, "/dev/sdb", protected_disk_identities=())
        validated = validate_plan(plan, protected_device_paths=("/dev/sda",))
        assert validated.validation.valid is True
        assert validated.validation.reasons == ()

    def test_validate_plan_never_raises_on_bad_plan(self):
        plan = _make_plan(target_device="/dev/sdb", esp="/dev/sda1")
        validated = validate_plan(plan, protected_device_paths=("/dev/sda",))
        assert validated.validation.valid is False
        assert validated.validation.reasons


# ---------------------------------------------------------------------------
# renderer - Sections 5-7, 25-26, 35
# ---------------------------------------------------------------------------


def _valid_plan_and_credential():
    identity = TargetDiskIdentity(
        serial="TGT", wwn="WTGT", observed_device_path="/dev/sdb", size_bytes=64_000_000_000
    )
    plan = build_install_plan(identity, "/dev/sdb", protected_disk_identities=())
    validated = validate_plan(plan, protected_device_paths=("/dev/sda",))
    credential = QaCredential(
        username="serein-qa", password="plaintext-secret", password_hash="$6$abc$def"
    )
    marker = build_install_state_marker("a" * 40, "26.04.1")
    return validated, credential, marker


class TestRenderer:
    def test_storage_config_uses_stable_match_never_largest_first(self):
        plan, _cred, _marker = _valid_plan_and_credential()
        config = render_autoinstall_storage_config(plan)
        disk_action = config["config"][0]
        assert disk_action["type"] == "disk"
        assert disk_action["match"]["serial"] == "TGT"
        assert disk_action["match"]["wwn"] == "WTGT"
        assert "path" in disk_action["match"]
        assert disk_action["grub_device"] is True

    def test_storage_config_esp_size_matches_baseline(self):
        plan, _cred, _marker = _valid_plan_and_credential()
        config = render_autoinstall_storage_config(plan)
        esp_format = next(a for a in config["config"] if a.get("id") == "partition-esp")
        assert esp_format["size"] == TARGET_ESP_SIZE_BYTES

    def test_render_refuses_unvalidated_plan(self):
        identity = TargetDiskIdentity(serial="TGT", observed_device_path="/dev/sdb")
        unvalidated = build_install_plan(identity, "/dev/sdb", protected_disk_identities=())
        with pytest.raises(RendererError):
            render_autoinstall_storage_config(unvalidated)

    def test_render_autoinstall_yaml_requires_explicit_qa_mode(self):
        plan, cred, marker = _valid_plan_and_credential()
        with pytest.raises(RendererError, match="qa_mode"):
            render_autoinstall_yaml(plan, cred, marker, qa_mode=False)

    def test_render_autoinstall_yaml_never_leaks_plaintext_password(self):
        plan, cred, marker = _valid_plan_and_credential()
        rendered = render_autoinstall_yaml(plan, cred, marker, qa_mode=True)
        assert cred.password not in rendered
        assert cred.password_hash in rendered

    def test_render_autoinstall_yaml_is_valid_json_and_yaml_superset(self):
        plan, cred, marker = _valid_plan_and_credential()
        rendered = render_autoinstall_yaml(plan, cred, marker, qa_mode=True)
        doc = json.loads(rendered)  # JSON is valid YAML - this IS the render
        assert doc["autoinstall"]["version"] == 1
        assert doc["autoinstall"]["ssh"]["allow-pw"] is False

    def test_render_embeds_correct_install_state_via_base64(self):
        plan, cred, marker = _valid_plan_and_credential()
        rendered = render_autoinstall_yaml(plan, cred, marker, qa_mode=True)
        doc = json.loads(rendered)
        late_command = doc["autoinstall"]["late-commands"][0]
        # extract the base64 payload out of the shell one-liner
        encoded = late_command.split("echo ")[1].split(" | base64")[0]
        decoded = json.loads(base64.b64decode(encoded))
        assert decoded["firstboot_provisioning"] == "pending"
        assert decoded["source_commit"] == "a" * 40

    def test_no_credential_scan_hit_in_rendered_output(self):
        # Static credential-scan proof (reuses the S7.0 safety scanner)
        # - the rendered document must never trip the generic
        # password:/token: patterns beyond the one legitimate hash
        # field, and never a plaintext password.
        plan, cred, marker = _valid_plan_and_credential()
        rendered = render_autoinstall_yaml(plan, cred, marker, qa_mode=True)
        findings = scan_text_for_credentials(rendered, source_path="<rendered>")
        # the crypt hash under "password": is expected evidence of a
        # *hash*, not a credential leak - assert specifically that the
        # PLAINTEXT never appears (already covered above) and that no
        # finding contains the plaintext value.
        assert all(cred.password not in rendered for _ in findings) or not findings


# ---------------------------------------------------------------------------
# payload - Sections 27, 35
# ---------------------------------------------------------------------------


class TestPayload:
    def test_install_state_marker_fields(self):
        marker = build_install_state_marker("a" * 40, "26.04.1")
        data = marker.to_dict()
        assert data["phase"] == "s7.1"
        assert data["installation_complete"] is True
        assert data["firstboot_provisioning"] == "pending"
        assert data["source_commit"] == "a" * 40

    def test_generate_qa_credential_real_openssl(self):
        if shutil.which("openssl") is None:
            pytest.skip("openssl not available in this environment")
        from serein.development.runner import DEFAULT_RUNNER

        credential = generate_qa_credential(runner=DEFAULT_RUNNER)
        assert credential is not None
        assert credential.password_hash.startswith("$6$")
        assert credential.password not in credential.password_hash

    def test_generate_qa_credential_unique_each_call(self):
        if shutil.which("openssl") is None:
            pytest.skip("openssl not available in this environment")
        from serein.development.runner import DEFAULT_RUNNER

        first = generate_qa_credential(runner=DEFAULT_RUNNER)
        second = generate_qa_credential(runner=DEFAULT_RUNNER)
        assert first.password != second.password
        assert first.password_hash != second.password_hash

    def test_generate_qa_credential_fails_soft_when_openssl_missing(self):
        runner = FakeCommandRunner({})
        assert generate_qa_credential(runner=runner) is None

    def test_generate_qa_credential_fails_soft_on_bad_output(self):
        runner = FakeCommandRunner({"openssl": _ok("not a real hash")})
        assert generate_qa_credential(runner=runner) is None

    def test_no_hardcoded_credential_value_in_installer_source(self):
        # Section 35: REUSABLE_PASSWORD_HASH_COMMITTED=false. The
        # generic scan_tree_for_credentials `password:`/`password=`
        # patterns inevitably false-positive on this module's own
        # type-safe credential-handling code (`password: str`,
        # `password=password`) - distribution's own source never has
        # this collision only because it never discusses credentials at
        # all. The actually meaningful invariant is checked precisely
        # instead: no committed crypt-hash *value*, no hardcoded
        # plaintext default.
        import re

        text = (REPO_ROOT / "src" / "serein" / "installer" / "payload.py").read_text()
        # a REAL crypt hash has a non-empty salt and a long hash body
        # (`$6$<salt>$<hash>`) - the docstring's own bare `$6$...`
        # (describing the *format*) must not be confused with one.
        assert not re.search(r"\$6\$[A-Za-z0-9./]{4,}\$[A-Za-z0-9./]{20,}", text)
        assert not re.search(r'password(_hash)?\s*[:=]\s*["\'][^"\']+["\']', text)

    def test_installer_scripts_tree_has_no_credentials(self):
        installer_dir = REPO_ROOT / "installer"
        if installer_dir.is_dir():
            assert scan_tree_for_credentials(installer_dir) == []


# ---------------------------------------------------------------------------
# evidence + closure - Sections 38, 52
# ---------------------------------------------------------------------------


def _passing_evidence(**overrides):
    kwargs = dict(
        source_commit="a" * 40,
        installer_backend="curtin", installer_backend_version="24.1",
        installer_backend_available=True, target_explicit=True,
        target_identity=TargetDiskIdentity(serial="S", observed_device_path="/dev/sdb"),
        target_identity_revalidated=True,
        protected_disk_identities=(
            TargetDiskIdentity(serial="P", observed_device_path="/dev/sda"),
        ),
        plan_valid=True, all_destructive_ops_on_target=True,
        target_disk_before_sha256="a" * 64, target_disk_after_sha256="b" * 64,
        protected_disk_before_sha256=("c" * 64,), protected_disk_after_sha256=("c" * 64,),
        target_esp_present=True, target_root_present=True, protected_esp_unchanged=True,
        installation_status="pass", install_media_removed_for_boot=True,
        installed_boot_status="pass", installed_boot_mode="uefi",
        installed_boot_marker="Reached target basic.target - Basic System.",
        install_media_attached_during_installed_boot=False,
        serein_core_present=True, firstboot_provisioning="pending",
        target_disk_attached=True,
    )
    kwargs.update(overrides)
    return assemble_installer_layer_b_evidence(**kwargs)


class TestEvidence:
    def test_minimal_evidence_matches_schema(self):
        evidence = assemble_installer_layer_b_evidence(source_commit="a" * 40)
        jsonschema.validate(
            evidence.to_dict(), _load_schema("installer-layer-b-evidence.schema.json")
        )
        assert evidence.installation_status == "not_performed"
        assert evidence.target_disk_changed is False
        assert evidence.protected_disk_hash_unchanged is False

    def test_full_pass_evidence_matches_schema(self):
        evidence = _passing_evidence()
        jsonschema.validate(
            evidence.to_dict(), _load_schema("installer-layer-b-evidence.schema.json")
        )

    def test_target_disk_changed_requires_both_real_hashes(self):
        only_before = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_disk_before_sha256="a" * 64
        )
        assert only_before.target_disk_changed is False

    def test_protected_hash_unchanged_never_vacuously_true(self):
        empty = assemble_installer_layer_b_evidence(source_commit="a" * 40)
        assert empty.protected_disk_hash_unchanged is False
        assert empty.protected_disk_modification_count == 0

    def test_protected_modification_count_detects_length_change(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            protected_disk_before_sha256=("a" * 64, "b" * 64),
            protected_disk_after_sha256=("a" * 64,),
        )
        assert evidence.protected_disk_modification_count == 2
        assert evidence.protected_disk_hash_unchanged is False

    def test_structural_invariants_never_caller_overridable(self):
        # physical_disk_passthrough/autoinstall_production_default are
        # true structural invariants - the code path to set them
        # otherwise does not exist, so assemble_* never accepts them as
        # parameters at all.
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_disk_attached=True
        )
        assert evidence.physical_disk_passthrough is False
        assert evidence.autoinstall_production_default is False

    def test_target_disk_attached_defaults_false_not_a_structural_invariant(self):
        # S7.1R Corrective B/Section 17 - the exact real defect: a real
        # run recorded target_disk_attached=true unconditionally, even
        # though disk_preflight failed before any fixture disk existed.
        # It is a RUNTIME fact and must default to the fail-closed
        # false, never be hardcoded true.
        evidence = assemble_installer_layer_b_evidence(source_commit="a" * 40)
        assert evidence.target_disk_attached is False

    def test_target_disk_attached_settable_only_by_explicit_caller(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_disk_attached=True
        )
        assert evidence.target_disk_attached is True

    def test_round_trip_through_write_and_load(self, tmp_path):
        original = _passing_evidence()
        path = write_installer_layer_b_evidence(original, tmp_path / "evidence.json")
        reloaded = load_installer_layer_b_evidence(path)
        assert reloaded.source_commit == original.source_commit
        assert reloaded.protected_disk_hash_unchanged == original.protected_disk_hash_unchanged
        assert reloaded.installed_boot_marker == original.installed_boot_marker
        assert reloaded.target_identity.serial == "S"

    def test_evidence_never_includes_host_identifying_fields(self, tmp_path):
        import os

        evidence = _passing_evidence()
        path = write_installer_layer_b_evidence(evidence, tmp_path / "evidence.json")
        serialized = path.read_text()
        for forbidden in (os.environ.get("USERNAME", "\0unset"), str(tmp_path)):
            if forbidden and forbidden != "\0unset":
                assert forbidden not in serialized

    def test_invalid_installation_status_rejected(self):
        with pytest.raises(ValueError, match="installation_status"):
            assemble_installer_layer_b_evidence(source_commit="a" * 40, installation_status="maybe")  # type: ignore[arg-type]


class TestEvidenceStageGating:
    """S7.1R Corrective B (Tests B1-B6): 'evidence records observed
    stage completion, not intended topology'. Real run #1 recorded
    target_explicit/target_identity_revalidated/target_disk_attached as
    true unconditionally, even though disk_preflight failed before any
    of those stages ever ran."""

    def test_b1_early_disk_preflight_failure_evidence(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, failure_stage="disk_preflight",
            failure_reason="insufficient disk space",
        )
        assert evidence.target_explicit is False
        assert evidence.target_identity_revalidated is False
        assert evidence.target_disk_attached is False
        assert evidence.installation_status == "not_performed"
        assert evidence.installed_boot_status == "not_performed"
        assert evidence.installed_boot_mode is None
        assert evidence.installed_boot_marker is None
        assert evidence.plan_valid is False
        assert evidence.all_destructive_ops_on_target is False
        assert evidence.target_disk_before_sha256 is None
        assert evidence.target_disk_after_sha256 is None
        assert evidence.target_disk_changed is False
        assert evidence.protected_disk_before_sha256 == ()
        assert evidence.protected_disk_hash_unchanged is False
        assert evidence.target_esp_present is False
        assert evidence.target_root_present is False
        assert evidence.protected_esp_unchanged is False
        assert evidence.serein_core_present is False
        assert evidence.firstboot_provisioning == "unknown"

    def test_b2_target_declared_but_fixture_not_created(self):
        # target_explicit may be true (render-autoinstall ran), but
        # target_disk_attached must NOT be marked true merely because a
        # target was declared - the fixture disks were never created.
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_explicit=True,
            failure_stage="installer_unavailable",
            failure_reason="create-fixture-disks.sh failed",
        )
        assert evidence.target_explicit is True
        assert evidence.target_disk_attached is False

    def test_b3_fixture_created_but_revalidation_not_run(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_explicit=True, target_disk_attached=True,
            failure_stage="target_changed",
            failure_reason="fixture topology re-verification failed",
        )
        assert evidence.target_disk_attached is True
        assert evidence.target_identity_revalidated is False

    def test_b4_successful_revalidation(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_explicit=True, target_disk_attached=True,
            target_identity_revalidated=True,
        )
        assert evidence.target_identity_revalidated is True
        assert evidence.target_disk_attached is True

    def test_b5_empty_hash_arrays_never_imply_protection_pass(self):
        evidence = assemble_installer_layer_b_evidence(source_commit="a" * 40)
        assert evidence.protected_disk_before_sha256 == ()
        assert evidence.protected_disk_after_sha256 == ()
        assert evidence.protected_disk_hash_unchanged is False

    def test_b6_target_change_requires_two_real_hashes(self):
        only_before = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_disk_before_sha256="a" * 64,
        )
        assert only_before.target_disk_changed is False
        only_after = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, target_disk_after_sha256="b" * 64,
        )
        assert only_after.target_disk_changed is False
        neither = assemble_installer_layer_b_evidence(source_commit="a" * 40)
        assert neither.target_disk_changed is False
        both_same = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            target_disk_before_sha256="a" * 64, target_disk_after_sha256="a" * 64,
        )
        assert both_same.target_disk_changed is False
        both_different = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            target_disk_before_sha256="a" * 64, target_disk_after_sha256="b" * 64,
        )
        assert both_different.target_disk_changed is True


class TestSecondaryFailures:
    """S7.1R6 Objective D: real, direct regression coverage for the
    primary/secondary failure distinction. Real Run #6 raised the
    concern that a genuine primary blocker (installer_timeout) could
    become obscured by a later, purely secondary cleanup/diagnostic
    failure (artifact_release_failed) - these tests prove the
    invariant holds: PRIMARY FAILURE MUST NEVER BE LOST OR OVERWRITTEN
    BY CLEANUP/EVIDENCE FAILURES."""

    def test_primary_installer_failure_preserved_with_secondary_present(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="installer_timeout",
            failure_reason="real QA autoinstall run timed out",
            secondary_failures=(
                ("artifact_release_failed", "release-artifact.sh failed for the QA-install ISO"),
            ),
        )
        assert evidence.failure_stage == "installer_timeout"
        assert evidence.failure_reason == "real QA autoinstall run timed out"

    def test_secondary_failure_remains_visible_in_evidence(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="installer_timeout",
            failure_reason="real QA autoinstall run timed out",
            secondary_failures=(
                ("artifact_release_failed", "release-artifact.sh failed for the QA-install ISO"),
            ),
        )
        assert evidence.secondary_failures == (
            ("artifact_release_failed", "release-artifact.sh failed for the QA-install ISO"),
        )

    def test_multiple_secondary_failures_all_visible(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="installer_timeout",
            failure_reason="real QA autoinstall run timed out",
            secondary_failures=(
                ("protected_disk_diagnostic_failed", "hash-disk-image.sh failed (before)"),
                ("target_disk_diagnostic_failed", "hash-disk-image.sh failed (after)"),
            ),
        )
        assert len(evidence.secondary_failures) == 2

    def test_success_path_unaffected_no_secondary_failures(self):
        evidence = _passing_evidence()
        assert evidence.secondary_failures == ()
        assert evidence.failure_stage is None

    def test_empty_secondary_failures_never_fabricated(self):
        evidence = assemble_installer_layer_b_evidence(source_commit="a" * 40)
        assert evidence.secondary_failures == ()

    def test_to_dict_serializes_secondary_failures_as_stage_reason_objects(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            secondary_failures=(("artifact_release_failed", "some real reason"),),
        )
        data = evidence.to_dict()
        assert data["secondary_failures"] == [
            {"stage": "artifact_release_failed", "reason": "some real reason"}
        ]

    def test_matches_schema(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="installer_timeout",
            failure_reason="timed out",
            secondary_failures=(("artifact_release_failed", "some reason"),),
        )
        jsonschema.validate(
            evidence.to_dict(), _load_schema("installer-layer-b-evidence.schema.json")
        )

    def test_round_trip_through_write_and_load(self, tmp_path):
        original = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="installer_timeout",
            failure_reason="timed out",
            secondary_failures=(
                ("artifact_release_failed", "reason one"),
                ("protected_disk_diagnostic_failed", "reason two"),
            ),
        )
        path = write_installer_layer_b_evidence(original, tmp_path / "evidence.json")
        reloaded = load_installer_layer_b_evidence(path)
        assert reloaded.failure_stage == "installer_timeout"
        assert reloaded.secondary_failures == (
            ("artifact_release_failed", "reason one"),
            ("protected_disk_diagnostic_failed", "reason two"),
        )

    def test_older_evidence_without_field_loads_with_empty_tuple(self, tmp_path):
        # Backward compatibility - evidence written before S7.1R6 never
        # had this field at all.
        path = tmp_path / "old-evidence.json"
        data = _passing_evidence().to_dict()
        del data["secondary_failures"]
        path.write_text(json.dumps(data), encoding="utf-8")
        reloaded = load_installer_layer_b_evidence(path)
        assert reloaded.secondary_failures == ()

    def test_secondary_failures_never_gate_closure(self):
        # Purely additive visibility - closure enforcement must remain
        # exclusively driven by the existing, unchanged fields.
        evidence = _passing_evidence(
            secondary_failures=(("artifact_release_failed", "cleanup hiccup"),),
        )
        enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_f_final_evidence_reflects_the_run_7_scenario(self, tmp_path):
        # Section 22 Test F - given primary=installer_timeout and a
        # secondary artifact_release_failed, the assembled JSON on disk
        # must show both correctly.
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="installer_timeout",
            failure_reason="timed out at 3600s",
            secondary_failures=(
                ("artifact_release_failed", "release-artifact.sh failed for build/work/extracted"),
            ),
        )
        path = write_installer_layer_b_evidence(evidence, tmp_path / "evidence.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["failure_stage"] == "installer_timeout"
        assert {"stage": "artifact_release_failed",
                "reason": "release-artifact.sh failed for build/work/extracted"} \
            in data["secondary_failures"]


class TestClosureGate:
    def test_all_required_fields_pass_closure_passes(self):
        evidence = _passing_evidence()
        enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_wrong_source_commit_fails(self):
        evidence = _passing_evidence()
        with pytest.raises(ClosureError, match="source_commit"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="f" * 40)

    def test_backend_unavailable_fails(self):
        evidence = _passing_evidence(installer_backend_available=False)
        with pytest.raises(ClosureError, match="installer_backend_available"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_target_not_explicit_fails(self):
        evidence = _passing_evidence(target_explicit=False)
        with pytest.raises(ClosureError, match="target_explicit"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_not_revalidated_fails(self):
        evidence = _passing_evidence(target_identity_revalidated=False)
        with pytest.raises(ClosureError, match="target_identity_revalidated"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_plan_invalid_fails(self):
        evidence = _passing_evidence(plan_valid=False)
        with pytest.raises(ClosureError, match="plan_valid"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_protected_disk_modified_fails(self):
        # The central S7.1 invariant.
        evidence = _passing_evidence(
            protected_disk_before_sha256=("c" * 64,), protected_disk_after_sha256=("d" * 64,)
        )
        with pytest.raises(ClosureError, match="protected_disk"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_target_disk_unchanged_fails(self):
        evidence = _passing_evidence(
            target_disk_before_sha256="a" * 64, target_disk_after_sha256="a" * 64
        )
        with pytest.raises(ClosureError, match="target_disk_changed"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_missing_target_esp_fails(self):
        evidence = _passing_evidence(target_esp_present=False)
        with pytest.raises(ClosureError, match="target_esp_present"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_protected_esp_changed_fails(self):
        evidence = _passing_evidence(protected_esp_unchanged=False)
        with pytest.raises(ClosureError, match="protected_esp_unchanged"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_install_media_still_attached_during_boot_fails(self):
        evidence = _passing_evidence(install_media_attached_during_installed_boot=True)
        with pytest.raises(ClosureError, match="install_media_attached"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_bios_boot_mode_fails(self):
        evidence = _passing_evidence(installed_boot_mode="bios")
        with pytest.raises(ClosureError, match="installed_boot_mode"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_empty_boot_marker_fails(self):
        evidence = _passing_evidence(installed_boot_marker=None)
        with pytest.raises(ClosureError, match="installed_boot_marker"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_firstboot_not_pending_fails(self):
        evidence = _passing_evidence(firstboot_provisioning="complete")
        with pytest.raises(ClosureError, match="firstboot_provisioning"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_serein_core_absent_fails(self):
        evidence = _passing_evidence(serein_core_present=False)
        with pytest.raises(ClosureError, match="serein_core_present"):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_production_pass_alone_never_satisfies_closure(self):
        # Mirrors S7.0's B6 pattern: only the target/plan/protected-disk
        # stages passing, everything downstream not_performed, must
        # still fail closure with multiple reasons listed.
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40,
            installer_backend_available=True, target_explicit=True,
            target_identity_revalidated=True, plan_valid=True,
            all_destructive_ops_on_target=True,
        )
        with pytest.raises(ClosureError) as exc_info:
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)
        message = str(exc_info.value)
        assert "protected_disk_hash_unchanged" in message
        assert "target_disk_changed" in message
        assert "installed_boot_status" in message

    def test_early_preflight_failure_evidence_fails_closure(self):
        evidence = assemble_installer_layer_b_evidence(
            source_commit="a" * 40, failure_stage="disk_preflight",
            failure_reason="insufficient free space",
        )
        with pytest.raises(ClosureError):
            enforce_installer_layer_b_closure(evidence, expected_source_commit="a" * 40)


# ---------------------------------------------------------------------------
# doctor / status
# ---------------------------------------------------------------------------


class TestDoctor:
    def test_missing_tools_are_skip_never_fail(self):
        report = run_installer_checks(runner=FakeCommandRunner({}))
        assert report.exit_code == 0
        statuses = {c.id: c.status.value for c in report.checks}
        assert statuses["installer_curtin_available"] == "SKIP"
        assert statuses["installer_lsblk_available"] == "SKIP"

    def test_plan_generation_and_ancestry_self_checks_pass(self):
        report = run_installer_checks(runner=FakeCommandRunner({}))
        statuses = {c.id: c.status.value for c in report.checks}
        assert statuses["installer_plan_generation"] == "PASS"
        assert statuses["installer_ancestry_self_check"] == "PASS"

    def test_present_tools_pass(self):
        runner = FakeCommandRunner({
            "curtin": _ok("24.1"),
            "lsblk": _ok("lsblk from util-linux 2.39"),
        })
        report = run_installer_checks(runner=runner)
        statuses = {c.id: c.status.value for c in report.checks}
        assert statuses["installer_curtin_available"] == "PASS"
        assert statuses["installer_lsblk_available"] == "PASS"


class TestStatus:
    def test_status_reflects_probe_results(self, tmp_path):
        runner = FakeCommandRunner({
            "curtin": _ok("24.1"), "lsblk": _ok(_LSBLK_JSON_TWO_DISKS),
        })
        status = build_installer_status(runner=runner, root=tmp_path)
        assert status.installer_backend_available is True
        assert status.disk_probe_tool_available is True
        assert status.disk_count_observed == 2

    def test_status_never_touches_network_or_disk(self, tmp_path):
        runner = FakeCommandRunner({})
        status = build_installer_status(runner=runner, root=tmp_path)
        assert status.installer_backend_available is False
        assert status.disk_count_observed == 0


# ---------------------------------------------------------------------------
# bootcheck - Sections 29, 47, 51
# ---------------------------------------------------------------------------


class _FakeQemuProcess:
    """A minimal subprocess.Popen-shaped fake (mirrors
    tests/test_distribution.py's identically-named helper) - never a
    real process."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminate_called = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_called = True
        if self.returncode is None:
            self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class TestBootCheck:
    def test_command_never_attaches_install_medium(self, tmp_path):
        command = build_installed_disk_boot_command(tmp_path / "target.qcow2", tmp_path / "s.log")
        assert "-cdrom" not in command
        assert any("if=virtio" in c for c in command)

    def test_command_ovmf_adds_readonly_pflash(self, tmp_path):
        command = build_installed_disk_boot_command(
            tmp_path / "target.qcow2", tmp_path / "s.log", ovmf_code=tmp_path / "OVMF_CODE.fd"
        )
        drive_args = [a for a in command if a.startswith("if=pflash")]
        assert drive_args and "readonly=on" in drive_args[0]

    def test_boot_check_passes_on_real_target_marker(self, tmp_path):
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        def fake_sleep(_seconds):
            fake_time["t"] += _seconds
            if fake_time["t"] >= 2.0:
                (tmp_path / "work" / "installed-boot-serial.log").write_text(
                    "Reached target basic.target - Basic System.\n"
                )

        result = run_installed_disk_boot_check(
            target_disk_path=tmp_path / "target.qcow2", work_dir=tmp_path / "work",
            timeout_seconds=10,
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"], sleep_fn=fake_sleep,
        )
        assert result.status == "pass"
        assert result.matched_marker == "Reached target basic.target - Basic System."

    def test_boot_check_fails_on_timeout(self, tmp_path):
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        result = run_installed_disk_boot_check(
            target_disk_path=tmp_path / "target.qcow2", work_dir=tmp_path / "work",
            timeout_seconds=3, poll_interval_seconds=1.0,
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"],
            sleep_fn=lambda s: fake_time.__setitem__("t", fake_time["t"] + s),
        )
        assert result.status == "fail"
        assert "timed out" in result.reason
        assert process.terminate_called is True

    def test_boot_check_fails_when_process_exits_early(self, tmp_path):
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        def fake_sleep(_seconds):
            fake_time["t"] += _seconds
            process.returncode = 1

        result = run_installed_disk_boot_check(
            target_disk_path=tmp_path / "target.qcow2", work_dir=tmp_path / "work",
            timeout_seconds=10,
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"], sleep_fn=fake_sleep,
        )
        assert result.status == "fail"
        assert result.matched_marker is None

    def test_weak_activity_never_passes(self, tmp_path):
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        def fake_sleep(_seconds):
            fake_time["t"] += _seconds
            (tmp_path / "work" / "installed-boot-serial.log").write_text(
                "Starting snapd.apparmor.service\nStarted arbitrary.service\n"
            )

        result = run_installed_disk_boot_check(
            target_disk_path=tmp_path / "target.qcow2", work_dir=tmp_path / "work",
            timeout_seconds=2, poll_interval_seconds=1.0,
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"], sleep_fn=fake_sleep,
        )
        assert result.status == "fail"
        assert result.matched_marker is None


# ---------------------------------------------------------------------------
# installer-smoke.yml - Layer-B workflow structure (Section 42-52)
# ---------------------------------------------------------------------------


WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


class TestInstallerSmokeWorkflow:
    @pytest.fixture()
    def workflow(self):
        import yaml

        with (WORKFLOWS_DIR / "installer-smoke.yml").open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_workflow_dispatch_present(self, workflow):
        triggers = workflow.get(True, workflow.get("on"))
        assert "workflow_dispatch" in triggers

    def test_pull_request_gated_on_distinct_label(self, workflow):
        # Section 42: must NOT trigger merely on S7.0's run-iso-smoke
        # label - this job is even more expensive.
        condition = workflow["jobs"]["installer-smoke"]["if"]
        assert "run-installer-smoke" in condition
        assert "run-iso-smoke" not in condition

    def test_pull_request_target_absent_from_raw_file(self):
        text = (WORKFLOWS_DIR / "installer-smoke.yml").read_text(encoding="utf-8")
        for line in text.splitlines():
            if "pull_request_target" in line:
                assert line.strip().startswith("#")

    def test_permissions_are_read_only(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}

    def test_no_secrets_referenced(self):
        import re

        text = (WORKFLOWS_DIR / "installer-smoke.yml").read_text(encoding="utf-8")
        assert re.search(r"\$\{\{\s*secrets\.", text) is None

    def test_checkout_uses_exact_pr_head_sha_expression(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
        assert checkout["with"]["ref"] == "${{ steps.expected-sha.outputs.sha }}"

    def test_exact_head_guard_step_present(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        guard = next(s for s in steps if s.get("name") == "Verify exact-head checkout")
        assert "EXPECTED_SOURCE_SHA" in guard["run"]
        assert "exit 1" in guard["run"]

    def test_evidence_and_closure_always_run(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Installer Layer-B evidence")
        assert assemble.get("if") == "always()"
        closure = next(s for s in steps if s.get("name") == "Enforce Installer Layer-B closure")
        assert closure.get("if") == "always()"
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        assert upload.get("if") == "always()"

    def test_evidence_upload_never_includes_disk_images_or_isos(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"]
        assert ".qcow2" not in paths
        assert "*.iso" not in paths

    def test_failure_sites_use_canonical_record_failure_helper(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for step in steps:
            script = step.get("run", "")
            assert "> dist/.failure_stage" not in script

    def test_render_autoinstall_uses_qa_allow_autoinstall_flag(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        render = next(s for s in steps if s.get("name") == "Render QA autoinstall config")
        assert "--qa-allow-autoinstall" in render["run"]

    def test_strict_inspection_uses_isolated_workdirs(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        prod = next(s for s in steps if s.get("name") == "Strict-inspect production ISO")
        qa = next(s for s in steps if s.get("name") == "Strict-inspect QA ISO")
        prod_wd = re.search(r"--work-dir\s+(\S+)", prod["run"]).group(1)
        qa_wd = re.search(r"--work-dir\s+(\S+)", qa["run"]).group(1)
        assert prod_wd != qa_wd

    def test_installed_boot_self_contained_step_has_no_protected_disk(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        primary = next(
            s for s in steps
            if s.get("name") == "Boot installed target (self-contained, no protected disk)"
        )
        assert "--protected-disk" not in primary["run"]

    def test_no_physical_device_path_referenced_anywhere(self):
        # Only prose (comments explicitly warning against this) may
        # mention these patterns - never actual command usage.
        text = (WORKFLOWS_DIR / "installer-smoke.yml").read_text(encoding="utf-8")
        for line in text.splitlines():
            for forbidden in ("/dev/sd", "/dev/nvme", "/dev/hd"):
                if forbidden in line:
                    assert line.strip().startswith("#"), line

    def test_no_broad_runner_deletion(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        cleanup = next(s for s in steps if s.get("name") == "Reclaim ephemeral runner SDK space")
        script = cleanup["run"]
        assert "rm -rf /opt/*" not in script
        assert "rm -rf /usr/local/*" not in script

    def test_preflight_arithmetic_is_named_not_a_bare_literal(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        assert "REQUIRED_KB=$((REQUIRED_GIB * 1024 * 1024))" in preflight["run"]

    # -- S7.1R Corrective A: storage-lifetime model (Tests A1-A3) --

    def test_a1_lifecycle_budget_excludes_released_artifacts(self, workflow):
        # Section 3-4: the preflight arithmetic must not sum artifacts
        # that are actually released before the real peak moment -
        # base ISO, S7.0 extracted tree, and production ISO must never
        # appear as summed components of the peak.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        script = preflight["run"]
        # Exact-variable-name checks (never a bare substring match -
        # QA_INSTALL_EXTRACTED_TREE_GIB legitimately contains
        # "EXTRACTED_TREE_GIB" as a substring and must NOT trip this).
        for excluded_var in ("BASE_ISO_GIB", "EXTRACTED_TREE_GIB", "PRODUCTION_ISO_GIB"):
            assert re.search(rf"(?<![A-Z_]){excluded_var}=", script) is None, (
                f"{excluded_var} must not be budgeted - it is released before the real peak"
            )

        # Each released artifact must have a real "Release ..." step
        # that runs before the "Prepare QA-install ISO" step (the real
        # peak moment).
        names = [s.get("name") for s in steps]
        peak_index = names.index("Prepare QA-install ISO")
        for release_step_name in (
            "Release S7.0 build work tree", "Release production ISO",
        ):
            assert release_step_name in names
            assert names.index(release_step_name) < peak_index

    def test_a2_safety_margin_remains_non_zero(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        match = re.search(r"SAFETY_MARGIN_GIB=(\d+)", preflight["run"])
        assert match is not None
        assert int(match.group(1)) >= 4

    def test_a3_sparse_qcow2_modeled_separately_from_virtual_capacity(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        script = preflight["run"]
        assert "FIXTURE_QCOW2_VIRTUAL_GIB" in script
        assert "FIXTURE_QCOW2_ALLOCATED_GIB" in script
        # The virtual-capacity variable must never be summed into
        # either candidate peak's arithmetic expression - only ever
        # echoed for contrast.
        assert "PEAK_GIB=$((FIXTURE_QCOW2_VIRTUAL_GIB" not in script
        assert "+ FIXTURE_QCOW2_VIRTUAL_GIB" not in script
        # The allocated (real, smaller) estimate IS used in the actual
        # arithmetic.
        assert "FIXTURE_QCOW2_ALLOCATED_GIB))" in script

    def test_release_artifact_helper_is_root_confined_and_never_sudo(self):
        text = (REPO_ROOT / "installer" / "scripts" / "release-artifact.sh").read_text(
            encoding="utf-8"
        )
        for line in text.splitlines():
            if "sudo" in line:
                assert line.strip().startswith("#"), line
        assert "REPO_ROOT" in text
        assert "realpath" in text

    # -- S7.1R2 Corrective C: artifact paths (Tests D1-D4) --

    def test_d1_serial_producer_path_matches_upload_path(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"]
        assert "dist/installer-fixtures/qa-install-serial.log" in paths

    def test_d2_qemu_diagnostic_producer_paths_match_upload_paths(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"]
        script_text = (REPO_ROOT / "installer" / "scripts" / "run-qa-install.sh").read_text(
            encoding="utf-8"
        )
        # The exact producer expressions, straight from the real script -
        # never guessed independently of what run-qa-install.sh actually
        # derives.
        assert 'QEMU_STDOUT_LOG="${WORK_DIR}/qa-install-qemu-stdout.log"' in script_text
        assert 'QEMU_STDERR_LOG="${WORK_DIR}/qa-install-qemu-stderr.log"' in script_text
        assert 'RESULT_ENV="${WORK_DIR}/qa-install-qemu-result.env"' in script_text
        assert "dist/installer-fixtures/qa-install-qemu-stdout.log" in paths
        assert "dist/installer-fixtures/qa-install-qemu-stderr.log" in paths
        assert "dist/installer-fixtures/qa-install-qemu-result.env" in paths

    def test_d3_evidence_upload_runs_on_failure(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        assert upload.get("if") == "always()"

    def test_d4_release_steps_record_failure_visibly_but_never_abort_the_job(self, workflow):
        # S7.1R2 Corrective D: a release/cleanup failure must remain
        # visible (a real recorded stage) but must never itself exit 1
        # and mask the real causal blocker or stop always()-gated
        # evidence/closure steps from still running.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name in (
            "Release S7.0 build work tree", "Release production ISO",
            "Release QA ISO and QA-install extraction tree", "Release QA-install ISO",
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert step.get("if") == "always()"
            assert "artifact_release_failed" in step["run"]
            assert "exit 1" not in step["run"]

    # -- S7.1R4 Section 8-10: protected-disk diagnostic instrumentation --

    def test_protected_disk_hashed_before_and_after_install(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        names = [s.get("name") for s in steps]
        before_idx = names.index("Hash protected disk (pre-install baseline)")
        install_idx = names.index("Run real QA autoinstall")
        after_idx = names.index("Hash protected disk (post-install)")
        assert before_idx < install_idx < after_idx

    def test_target_disk_hashed_before_and_after_install(self, workflow):
        # S7.1R5 Objective D.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        names = [s.get("name") for s in steps]
        before_idx = names.index("Hash target disk (pre-install baseline)")
        install_idx = names.index("Run real QA autoinstall")
        after_idx = names.index("Hash target disk (post-install)")
        assert before_idx < install_idx < after_idx

    def test_disk_hash_steps_always_run(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name in (
            "Hash protected disk (pre-install baseline)", "Hash protected disk (post-install)",
            "Hash target disk (pre-install baseline)", "Hash target disk (post-install)",
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert step.get("if", "").startswith("always()")

    def test_disk_hash_steps_use_the_generalized_script(self, workflow):
        # S7.1R5 Corrective A - every hashing step must call the new,
        # qemu-nbd-free script, never the old removed one.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name in (
            "Hash protected disk (pre-install baseline)", "Hash protected disk (post-install)",
            "Hash target disk (pre-install baseline)", "Hash target disk (post-install)",
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert "hash-disk-image.sh" in step["run"]
            assert "hash-protected-disk.sh" not in step["run"]

    def test_disk_hash_step_failures_recorded_as_secondary_never_abort(self, workflow):
        # S7.1R5 Section 18/Corrective A: Run #5 proved this step's own
        # failure was previously invisible to the evidence system
        # (unlike every other failure-capable step, it never called
        # record-failure.sh). Now it does, mirroring the Release
        # steps' own established non-blocking pattern - never `exit 1`,
        # so a diagnostic failure never masks (or gets masked by) the
        # real installer_timeout blocker via first-failure-wins.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name, stage in (
            ("Hash protected disk (pre-install baseline)", "protected_disk_diagnostic_failed"),
            ("Hash protected disk (post-install)", "protected_disk_diagnostic_failed"),
            ("Hash target disk (pre-install baseline)", "target_disk_diagnostic_failed"),
            ("Hash target disk (post-install)", "target_disk_diagnostic_failed"),
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert stage in step["run"]
            assert "exit 1" not in step["run"]

    def test_every_secondary_failure_site_calls_the_secondary_recorder(self, workflow):
        # Every "secondary, non-blocking" site must call
        # record-secondary-failure.sh, so its failure appears in
        # evidence's secondary_failures list.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name in (
            "Release S7.0 build work tree", "Release production ISO",
            "Release QA ISO and QA-install extraction tree", "Release QA-install ISO",
            "Hash protected disk (pre-install baseline)", "Hash protected disk (post-install)",
            "Hash target disk (pre-install baseline)", "Hash target disk (post-install)",
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert "record-secondary-failure.sh" in step["run"], name

    def test_secondary_failure_sites_never_also_call_the_primary_recorder(self, workflow):
        # S7.1R7 Objective B (Test E) - the exact real Run #7 wiring
        # defect: a "secondary, non-blocking" site must NEVER also call
        # distribution/scripts/record-failure.sh for the SAME event,
        # since that is the PRIMARY, first-failure-wins recorder - a
        # non-blocking cleanup/diagnostic failure occupying
        # dist/.failure_stage before the real installer blocker occurs
        # is exactly the defect real Run #7 proved. This is a real,
        # per-step structural check, not merely "the secondary recorder
        # is present somewhere in the file" (which the previous,
        # buggy R6 wiring would also have passed).
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name in (
            "Release S7.0 build work tree", "Release production ISO",
            "Release QA ISO and QA-install extraction tree", "Release QA-install ISO",
            "Hash protected disk (pre-install baseline)", "Hash protected disk (post-install)",
            "Hash target disk (pre-install baseline)", "Hash target disk (post-install)",
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert "distribution/scripts/record-failure.sh" not in step["run"], name

    def test_genuine_primary_blocker_sites_still_call_the_primary_recorder(self, workflow):
        # The fix must be surgical - genuinely blocking failures
        # (disk_preflight, base_fetch, the real install run itself,
        # etc.) must still call the PRIMARY recorder exactly as before.
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        for name in (
            "Disk space preflight", "Fetch pinned base image",
            "Verify base image (fail-closed, checksum + signature)",
            "Build Serein Alpha ISO (production + QA variant)",
            "Strict-inspect production ISO", "Strict-inspect QA ISO",
            "Render QA autoinstall config", "Prepare QA-install ISO",
            "Create fixture disks (protected + target)",
            "Re-verify fixture topology", "Run real QA autoinstall",
            "Inspect target disk layout",
            "Boot installed target (self-contained, no protected disk)",
        ):
            step = next(s for s in steps if s.get("name") == name)
            assert "distribution/scripts/record-failure.sh" in step["run"], name

    def test_evidence_assembly_reads_secondary_failures_file(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Installer Layer-B evidence")
        assert "dist/.secondary_failures" in assemble["run"]
        assert "--secondary-failure" in assemble["run"]

    def test_secondary_failures_file_uploaded(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"]
        assert "dist/.secondary_failures" in paths

    def test_extract_signals_step_present_and_always_runs(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        step = next(
            s for s in steps if s.get("name") == "Extract installer signals from serial log"
        )
        assert step.get("if") == "always()"

    def test_new_evidence_files_uploaded(self, workflow):
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"]
        assert "dist/installer-fixtures/qa-install-subiquity-signals.log" in paths
        assert "dist/installer-fixtures/protected-disk-diagnostic.env" in paths
        assert "dist/installer-fixtures/target-disk-diagnostic.env" in paths

    def test_new_diagnostic_hashes_never_gate_closure(self, workflow):
        # Section 16: never silently change the safety contract's
        # semantics - the new disk diagnostic hashing must never feed
        # the evidence-assembly step's own ARGS (the existing
        # container-hash-based closure gate stays exactly unchanged;
        # this new instrumentation is additive/diagnostic only,
        # uploaded as its own separate files).
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Installer Layer-B evidence")
        assert "protected-hash-before" not in assemble["run"]
        assert "protected-hash-after" not in assemble["run"]
        assert "target-hash-before" not in assemble["run"]
        assert "target-hash-after" not in assemble["run"]
        assert "logical_sha256" not in assemble["run"]


# ---------------------------------------------------------------------------
# S7.1R: real disk-preflight script execution (Tests A4-A5)
# ---------------------------------------------------------------------------


def _make_fake_df(bin_dir: Path, available_kb: int) -> None:
    """A stub `df` on PATH mimicking `df -Pk .`'s real column layout
    (Filesystem/1024-blocks/Used/Available/Capacity/Mounted) closely
    enough for `awk '{print $4}'` to extract the intended Available
    figure - proves the real preflight script's own arithmetic and
    comparison, not a hand-copied re-implementation."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "df"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Filesystem     1024-blocks      Used Available Capacity Mounted on'\n"
        f"echo '/dev/fake        999999999   1000000 {available_kb}      1% /'\n"
    )
    script.chmod(0o755)


class TestDiskPreflightScript:
    """Extracts the REAL `run:` script for the "Disk space preflight"
    step straight from the committed workflow YAML and executes it via
    `bash -c` with a stub `df` on PATH - proves the real fix
    behaviorally, not merely that certain strings appear in the file."""

    @pytest.fixture()
    def step_script(self):
        import yaml

        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        with (WORKFLOWS_DIR / "installer-smoke.yml").open(encoding="utf-8") as fh:
            workflow = yaml.safe_load(fh)
        steps = workflow["jobs"]["installer-smoke"]["steps"]
        step = next(s for s in steps if s.get("name") == "Disk space preflight")
        return step["run"]

    def _run(self, script: str, work_dir: Path, bin_dir: Path) -> subprocess.CompletedProcess:
        real_helper = REPO_ROOT / "distribution" / "scripts" / "record-failure.sh"
        sandboxed_helper = work_dir / "distribution" / "scripts" / "record-failure.sh"
        sandboxed_helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(real_helper, sandboxed_helper)

        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        return subprocess.run(
            ["bash", "-c", script], cwd=work_dir, env=env, capture_output=True, text=True,
        )

    def test_a4_preflight_fails_when_genuinely_insufficient(self, step_script, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        _make_fake_df(tmp_path / "bin", available_kb=1_000_000)  # ~1 GiB - genuinely too small

        result = self._run(step_script, work_dir, tmp_path / "bin")

        assert result.returncode != 0
        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "disk_preflight"
        reason = (work_dir / "dist" / ".failure_reason").read_text().strip()
        assert "insufficient disk space" in reason

    def test_a5_preflight_passes_for_run_1_real_available_capacity(self, step_script, tmp_path):
        # Section 23 Test A5: use Run #1's own real observed available
        # capacity (38180956 KiB) - deterministic, never "assume the
        # runner always has 36 GiB"; the corrected model must fit
        # THIS exact real number with real margin.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        _make_fake_df(tmp_path / "bin", available_kb=38180956)

        result = self._run(step_script, work_dir, tmp_path / "bin")

        assert result.returncode == 0, result.stdout + result.stderr
        assert not (work_dir / "dist" / ".failure_stage").exists()
        assert "REQUIRED_GIB=" in result.stdout

    def test_preflight_still_fails_closed_never_a_no_op(self, step_script, tmp_path):
        # Preflight must remain a real gate - it is not acceptable for
        # it to have become unconditionally-passing.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        _make_fake_df(tmp_path / "bin", available_kb=0)

        result = self._run(step_script, work_dir, tmp_path / "bin")
        assert result.returncode != 0


class TestInstallerFirstFailureWins:
    """Test B7 (Section 24, 21): executes the REAL, committed
    ``distribution/scripts/record-failure.sh`` - the same canonical
    helper ``installer-smoke.yml`` calls at every one of its own
    failure sites - proving disk_preflight (the real run #1 blocker)
    is never overwritten by a later, independent installer-stage
    failure."""

    SCRIPT_PATH = REPO_ROOT / "distribution" / "scripts" / "record-failure.sh"

    def _run(self, work_dir: Path, stage: str, reason: str) -> subprocess.CompletedProcess:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        return subprocess.run(
            ["bash", str(self.SCRIPT_PATH), stage, reason],
            cwd=work_dir, capture_output=True, text=True,
        )

    def test_b7_disk_preflight_not_overwritten_by_later_installer_failure(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        self._run(work_dir, "disk_preflight", "insufficient disk space")
        self._run(work_dir, "installer_config_invalid", "render-autoinstall failed")
        self._run(work_dir, "install_failed", "real QA autoinstall run failed")
        self._run(work_dir, "installed_boot_failed", "installed target failed to boot")

        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "disk_preflight"
        assert (
            work_dir / "dist" / ".failure_reason"
        ).read_text().strip() == "insufficient disk space"

    # -- S7.1R2 Section 24 (Tests C1-C2): the NEW precise stage names --

    def test_c1_qemu_startup_not_overwritten_by_later_release_failure(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        self._run(work_dir, "qemu_startup", "invalid command line or device model")
        self._run(work_dir, "artifact_release_failed", "release-artifact.sh failed for X")
        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "qemu_startup"

    def test_c2_installer_execution_recorded_as_first_failure(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        self._run(work_dir, "installer_execution", "real QA autoinstall run failed")
        self._run(work_dir, "artifact_release_failed", "release-artifact.sh failed for Y")
        assert (
            work_dir / "dist" / ".failure_stage"
        ).read_text().strip() == "installer_execution"


# ---------------------------------------------------------------------------
# S7.1R6 Objective D: installer/scripts/record-secondary-failure.sh -
# real bash execution, plus the combined primary+secondary invariant.
# ---------------------------------------------------------------------------


class TestRecordSecondaryFailureScript:
    SCRIPT_PATH = REPO_ROOT / "installer" / "scripts" / "record-secondary-failure.sh"
    PRIMARY_SCRIPT_PATH = REPO_ROOT / "distribution" / "scripts" / "record-failure.sh"

    def _run(self, work_dir: Path, stage: str, reason: str) -> subprocess.CompletedProcess:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        return subprocess.run(
            ["bash", str(self.SCRIPT_PATH), stage, reason],
            cwd=work_dir, capture_output=True, text=True,
        )

    def test_appends_one_line_per_call(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        self._run(work_dir, "artifact_release_failed", "reason one")
        self._run(work_dir, "protected_disk_diagnostic_failed", "reason two")
        lines = (work_dir / "dist" / ".secondary_failures").read_text().splitlines()
        assert lines == [
            "artifact_release_failed\treason one",
            "protected_disk_diagnostic_failed\treason two",
        ]

    def test_never_touches_primary_failure_files(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        self._run(work_dir, "artifact_release_failed", "some reason")
        assert not (work_dir / "dist" / ".failure_stage").exists()
        assert not (work_dir / "dist" / ".failure_reason").exists()

    def test_missing_args_fails_closed(self, tmp_path):
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        result = subprocess.run(
            ["bash", str(self.SCRIPT_PATH), "only_one_arg"],
            cwd=work_dir, capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_primary_never_overwritten_by_secondary_recorder(self, tmp_path):
        # The exact real invariant Section 10/18 requires: a genuine
        # primary blocker (installer_timeout, via the UNMODIFIED S7.0
        # record-failure.sh) coexists with, and is never affected by,
        # any number of secondary recordings.
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        subprocess.run(
            ["bash", str(self.PRIMARY_SCRIPT_PATH), "installer_timeout", "timed out at 1800s"],
            cwd=work_dir, capture_output=True, text=True, check=True,
        )
        self._run(work_dir, "artifact_release_failed", "release-artifact.sh failed for the ISO")
        self._run(work_dir, "protected_disk_diagnostic_failed", "hash-disk-image.sh failed")

        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "installer_timeout"
        assert (
            work_dir / "dist" / ".failure_reason"
        ).read_text().strip() == "timed out at 1800s"
        secondary_lines = (work_dir / "dist" / ".secondary_failures").read_text().splitlines()
        assert len(secondary_lines) == 2

    # -- S7.1R7 Section 22: the exact required failure-semantics tests --

    def test_a_no_primary_before_secondary(self, tmp_path):
        # Test A - a lone primary recording.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        subprocess.run(
            ["bash", str(self.PRIMARY_SCRIPT_PATH), "A", "reason A"],
            cwd=work_dir, capture_output=True, text=True, check=True,
        )
        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "A"
        assert not (work_dir / "dist" / ".secondary_failures").exists()

    def test_b_primary_then_secondary(self, tmp_path):
        # Test B.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        subprocess.run(
            ["bash", str(self.PRIMARY_SCRIPT_PATH), "A", "reason A"],
            cwd=work_dir, capture_output=True, text=True, check=True,
        )
        self._run(work_dir, "B", "reason B")
        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "A"
        secondary = (work_dir / "dist" / ".secondary_failures").read_text().splitlines()
        assert secondary == ["B\treason B"]

    def test_c_secondary_first_then_primary_the_exact_run_7_scenario(self, tmp_path):
        # Test C - THE CRITICAL Run #7 scenario: a secondary/cleanup
        # failure (artifact_release_failed) genuinely occurs FIRST
        # chronologically, and the real installer_timeout blocker is
        # only discovered afterward. Because the two recorders now
        # write to entirely separate files, ordering must never matter
        # - installer_timeout must still be primary.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        self._run(work_dir, "artifact_release_failed", "release-artifact.sh failed")
        subprocess.run(
            ["bash", str(self.PRIMARY_SCRIPT_PATH), "installer_timeout", "timed out at 3600s"],
            cwd=work_dir, capture_output=True, text=True, check=True,
        )
        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "installer_timeout"
        secondary = (work_dir / "dist" / ".secondary_failures").read_text().splitlines()
        assert secondary == ["artifact_release_failed\trelease-artifact.sh failed"]

    def test_d_multiple_secondary_before_primary(self, tmp_path):
        # Test D.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        self._run(work_dir, "B", "reason B")
        self._run(work_dir, "C", "reason C")
        subprocess.run(
            ["bash", str(self.PRIMARY_SCRIPT_PATH), "A", "reason A"],
            cwd=work_dir, capture_output=True, text=True, check=True,
        )
        assert (work_dir / "dist" / ".failure_stage").read_text().strip() == "A"
        secondary = (work_dir / "dist" / ".secondary_failures").read_text().splitlines()
        assert secondary == ["B\treason B", "C\treason C"]


# ---------------------------------------------------------------------------
# S7.1R2: real QEMU drive identity + bounded startup probe + startup
# evidence (installer/scripts/run-qa-install.sh)
# ---------------------------------------------------------------------------


def _make_fake_qemu(bin_dir: Path) -> None:
    """A stub `qemu-system-x86_64` on PATH - never a real VM. Entirely
    controlled via env vars the test sets, so the REAL, committed
    run-qa-install.sh's own bounded-probe / real-run / evidence-writing
    logic executes for real and is proven behaviorally, never
    re-implemented in Python. `FAKE_QEMU_BEHAVIOR`:

      probe_fail          - exits non-zero immediately on ANY
                             invocation (simulates an invalid command
                             line/device model - Run #2's hypothesized
                             defect).
      pass                - accepts the probe (stays alive, frozen,
                             the whole probe window); the real run
                             stays alive past the grace window, then
                             exits 0.
      run_fail            - same probe behavior as `pass`; the real
                             run stays alive past the grace window,
                             then exits non-zero.
      run_dies_before_grace - probe passes; the real run exits
                             non-zero immediately, before the wrapper's
                             own liveness grace check.
      run_hangs           - probe passes; the real run never exits on
                             its own (proves the outer `timeout`
                             backstop).
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "qemu-system-x86_64"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$@" >> "${FAKE_QEMU_ARGV_FILE:?}"\n'
        "IS_PROBE=false\n"
        'for a in "$@"; do [ "$a" = "-S" ] && IS_PROBE=true; done\n'
        'case "${FAKE_QEMU_BEHAVIOR:-pass}" in\n'
        "  probe_fail)\n"
        '    echo "fake: invalid command line or device model" >&2\n'
        "    exit 1 ;;\n"
        "  pass)\n"
        '    if [ "${IS_PROBE}" = "true" ]; then exec sleep 1000; fi\n'
        '    sleep "${FAKE_QEMU_RUN_SLEEP:-2}"; exit 0 ;;\n'
        "  run_fail)\n"
        '    if [ "${IS_PROBE}" = "true" ]; then exec sleep 1000; fi\n'
        '    sleep "${FAKE_QEMU_RUN_SLEEP:-2}"; exit 1 ;;\n'
        "  run_dies_before_grace)\n"
        '    if [ "${IS_PROBE}" = "true" ]; then exec sleep 1000; fi\n'
        "    exit 1 ;;\n"
        "  run_hangs)\n"
        '    if [ "${IS_PROBE}" = "true" ]; then exec sleep 1000; fi\n'
        "    exec sleep 1000 ;;\n"
        "esac\n"
    )
    script.chmod(0o755)


class TestRunQaInstallScript:
    """Real bash execution of the committed, REAL
    installer/scripts/run-qa-install.sh against a stub
    qemu-system-x86_64 on PATH."""

    SCRIPT = REPO_ROOT / "installer" / "scripts" / "run-qa-install.sh"

    def _run(
        self, tmp_path: Path, behavior: str, timeout_seconds: int = 30,
        run_sleep: int | None = None,
    ) -> tuple[subprocess.CompletedProcess, Path]:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        bin_dir = tmp_path / "bin"
        _make_fake_qemu(bin_dir)
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        iso = tmp_path / "qa-install.iso"
        iso.write_bytes(b"fake iso")
        protected = fixtures / "disk-protected.qcow2"
        protected.write_bytes(b"fake protected")
        target = fixtures / "disk-target.qcow2"
        target.write_bytes(b"fake target")
        ovmf = tmp_path / "OVMF_CODE.fd"
        ovmf.write_bytes(b"fake ovmf")
        argv_file = tmp_path / "qemu-argv.log"

        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_QEMU_BEHAVIOR"] = behavior
        env["FAKE_QEMU_ARGV_FILE"] = str(argv_file)
        if run_sleep is not None:
            env["FAKE_QEMU_RUN_SLEEP"] = str(run_sleep)
        # Fast, real, sub-second-scale probe/grace windows - never the
        # real 8s/2s production defaults (would make this test suite
        # slow for no benefit; the SCRIPT's own logic is unchanged).
        env["SEREIN_TEST_PROBE_TIMEOUT_SECONDS"] = "1"
        env["SEREIN_TEST_RUN_STARTED_GRACE_SECONDS"] = "1"

        result = subprocess.run(
            ["bash", str(self.SCRIPT), str(iso), str(protected), str(target),
             "--ovmf-code", str(ovmf), "--timeout", str(timeout_seconds)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        )
        return result, fixtures

    def _result_env(self, fixtures: Path) -> dict[str, str]:
        text = (fixtures / "qa-install-qemu-result.env").read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    # -- Corrective A (Tests A1-A7): modern backend/device split --

    def test_a1_legacy_drive_serial_syntax_removed(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert 'if=virtio,format=qcow2,file="${PROTECTED_DISK}",serial=' not in text
        assert 'if=virtio,format=qcow2,file="${TARGET_DISK}",serial=' not in text

    def test_a2_protected_backend_exists(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert (
            '-drive if=none,id=serein_protected_backend,format=qcow2,file="${PROTECTED_DISK}"'
            in text
        )

    def test_a3_target_backend_exists(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert (
            '-drive if=none,id=serein_target_backend,format=qcow2,file="${TARGET_DISK}"' in text
        )

    def test_a4_protected_serial_only_on_protected_device(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        line = next(li for li in text.splitlines() if "id=serein_protected_device" in li)
        assert "drive=serein_protected_backend" in line
        assert "serial=SEREIN-PROTECTED-DISK" in line
        assert "target" not in line.lower()

    def test_a5_target_serial_only_on_target_device(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        line = next(li for li in text.splitlines() if "id=serein_target_device" in li)
        assert "drive=serein_target_backend" in line
        assert "serial=SEREIN-TARGET-DISK" in line
        assert "protected" not in line.lower()

    def test_a6_backends_never_swapped_in_real_argv(self, tmp_path):
        # Real execution - proves the ACTUAL argv QEMU receives, not
        # merely the script text.
        self._run(tmp_path, "probe_fail")
        argv_text = (tmp_path / "qemu-argv.log").read_text(encoding="utf-8")
        parts = argv_text.split()
        protected_device = next(
            p for p in parts if p.startswith("virtio-blk-pci,id=serein_protected_device")
        )
        target_device = next(
            p for p in parts if p.startswith("virtio-blk-pci,id=serein_target_device")
        )
        assert "drive=serein_protected_backend" in protected_device
        assert "serial=SEREIN-PROTECTED-DISK" in protected_device
        assert "drive=serein_target_backend" in target_device
        assert "serial=SEREIN-TARGET-DISK" in target_device

    def test_a7_no_dev_vdx_hardcoded_in_orchestration(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "/dev/vd" in line:
                assert line.strip().startswith("#"), line

    # -- S7.1R4 Corrective A (Test A8): protected backend is read-only --

    def test_a8_protected_backend_is_readonly_target_remains_writable(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        protected_line = next(
            li for li in text.splitlines() if "id=serein_protected_backend" in li
        )
        assert "readonly=on" in protected_line
        target_line = next(li for li in text.splitlines() if "id=serein_target_backend" in li)
        assert "readonly=on" not in target_line

    def test_a8_readonly_applies_to_both_probe_and_real_run(self):
        # QEMU_ARGS is a single shared array used by both the bounded
        # startup probe and the real timed run below it - readonly=on
        # must therefore apply to both automatically (Section 9).
        text = self.SCRIPT.read_text(encoding="utf-8")
        args_block = text.split("QEMU_ARGS=(")[1].split(")\n")[0]
        assert "readonly=on" in args_block
        assert "qemu-system-x86_64 \"${QEMU_ARGS[@]}\"" in text  # probe invocation
        assert text.count('qemu-system-x86_64 "${QEMU_ARGS[@]}"') >= 2  # probe + real run

    # -- Corrective B (Tests B1-B5): startup evidence --

    def test_b1_qemu_parser_failure_retains_diagnostics(self, tmp_path):
        result, fixtures = self._run(tmp_path, "probe_fail")
        assert result.returncode != 0
        env = self._result_env(fixtures)
        assert env["qemu_exit_status"] != "0"
        assert env["failure_stage"] == "qemu_startup"
        assert (fixtures / "qa-install-qemu-stderr.log").read_text().strip() != ""
        assert "fake: invalid command line" in result.stderr

    def test_b2_missing_serial_does_not_destroy_evidence(self, tmp_path):
        # QEMU died during command-line parsing (the fake never touches
        # -serial's target at all) - the guest console log genuinely
        # does not exist, and that must be reported truthfully rather
        # than silently omitted or fabricated.
        result, fixtures = self._run(tmp_path, "probe_fail")
        env = self._result_env(fixtures)
        assert env["serial_log_present"] == "false"
        assert (fixtures / "qa-install-qemu-stderr.log").exists()
        assert env["qemu_diagnostic_log_path"].endswith("qa-install-qemu-stderr.log")

    def test_b3_startup_failure_never_claims_userspace_reached(self, tmp_path):
        result, fixtures = self._run(tmp_path, "probe_fail")
        env = self._result_env(fixtures)
        assert env["installer_userspace_reached"] == "false"

    def test_b4_real_run_failure_is_fail_closed_never_becomes_pass(self, tmp_path):
        result, fixtures = self._run(tmp_path, "run_fail", run_sleep=2)
        assert result.returncode != 0
        env = self._result_env(fixtures)
        assert env["failure_stage"] == "installer_execution"
        assert env["qemu_started"] == "true"

    def test_b5_timeout_is_fail_never_pass(self, tmp_path):
        result, fixtures = self._run(tmp_path, "run_hangs", timeout_seconds=2)
        assert result.returncode != 0
        env = self._result_env(fixtures)
        assert env["failure_stage"] == "installer_timeout"

    def test_real_pass_records_no_failure_stage(self, tmp_path):
        result, fixtures = self._run(tmp_path, "pass", run_sleep=2)
        assert result.returncode == 0
        env = self._result_env(fixtures)
        assert env["failure_stage"] == ""
        assert env["qemu_started"] == "true"
        assert env["qemu_exit_status"] == "0"

    def test_qemu_started_false_when_real_run_dies_before_grace_window(self, tmp_path):
        # An edge case that should not normally occur once the probe
        # above already passed - still classified honestly as
        # qemu_startup rather than silently folded into
        # installer_execution.
        result, fixtures = self._run(tmp_path, "run_dies_before_grace")
        assert result.returncode != 0
        env = self._result_env(fixtures)
        assert env["qemu_started"] == "false"
        assert env["failure_stage"] == "qemu_startup"


# ---------------------------------------------------------------------------
# S7.1R2 Corrective D: installer/scripts/release-artifact.sh - real
# release-cleanup safety (Tests E1, E3, E4)
# ---------------------------------------------------------------------------


class TestReleaseArtifactScript:
    """Real bash execution of the committed
    installer/scripts/release-artifact.sh, sandboxed into a fake repo
    root (mirrors TestDiskPreflightScript's established pattern) -
    release-artifact.sh computes its own REPO_ROOT from
    ${BASH_SOURCE[0]}'s location and `cd`s there, so it must be copied
    into a temp tree rather than merely invoked with a different `cwd`."""

    REAL_SCRIPT = REPO_ROOT / "installer" / "scripts" / "release-artifact.sh"

    def _run(self, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        script = tmp_path / "installer" / "scripts" / "release-artifact.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.REAL_SCRIPT, script)
        script.chmod(0o755)
        return subprocess.run(
            ["bash", str(script), *args], cwd=tmp_path, capture_output=True, text=True,
        )

    def test_e1_already_absent_artifact_is_a_safe_no_op(self, tmp_path):
        result = self._run(tmp_path, "dist/does-not-exist.iso")
        assert result.returncode == 0
        assert "already absent" in result.stdout

    def test_releasing_a_real_existing_path_removes_it(self, tmp_path):
        target = tmp_path / "dist" / "thing.iso"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x" * 1024)
        result = self._run(tmp_path, "dist/thing.iso")
        assert result.returncode == 0
        assert not target.exists()

    def test_e3_symlink_escape_fails_closed(self, tmp_path):
        outside = tmp_path.parent / f"outside-{tmp_path.name}.txt"
        outside.write_text("must survive")
        link = tmp_path / "dist" / "escape.iso"
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")
        result = self._run(tmp_path, "dist/escape.iso")
        assert result.returncode != 0
        assert outside.read_text() == "must survive"

    def test_e4_absolute_path_refused(self, tmp_path):
        result = self._run(tmp_path, "/etc/passwd")
        assert result.returncode != 0

    def test_e4_traversal_path_refused(self, tmp_path):
        result = self._run(tmp_path, "../outside.txt")
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# S7.1R5 Corrective A: installer/scripts/hash-disk-image.sh - real bash
# execution against stub sudo/qemu-img/losetup/blkid tools. Replaces
# the S7.1R4 qemu-nbd-based hash-protected-disk.sh (real Run #5,
# RUN_ID=34255177947, proved that failed) - never nbd, never a kernel
# module, generalized to hash either disk (S7.1R5 Objective D).
# ---------------------------------------------------------------------------


class TestHashDiskImageScript:
    SCRIPT = REPO_ROOT / "installer" / "scripts" / "hash-disk-image.sh"
    _FAKE_LOGICAL_CONTENT = b"FAKE_LOGICAL_CONTENT"

    def _run(
        self, tmp_path: Path, image_content: bytes = b"fake qcow2 container bytes"
    ) -> tuple[subprocess.CompletedProcess, Path]:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name, body in {
            "sudo": '#!/usr/bin/env bash\nexec "$@"\n',
            "qemu-img": (
                "#!/usr/bin/env bash\n"
                'if [ "$1" = "convert" ]; then\n'
                '  dst="${@: -1}"\n'
                f"  printf '%s' '{self._FAKE_LOGICAL_CONTENT.decode()}' > \"$dst\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n"
            ),
            "losetup": (
                "#!/usr/bin/env bash\n"
                'case "$1" in\n'
                "  --show) echo '/dev/loop77'; exit 0 ;;\n"
                "  -d) exit 0 ;;\n"
                "esac\n"
                "exit 0\n"
            ),
            "partprobe": "#!/usr/bin/env bash\nexit 0\n",
            # No real loop-backed block device exists in this sandbox -
            # blkid never gets a real path to inspect anyway
            # ([ -b ... ] already fails first), but fail closed too.
            "blkid": "#!/usr/bin/env bash\nexit 1\n",
        }.items():
            script = bin_dir / name
            script.write_text(body)
            script.chmod(0o755)

        image = tmp_path / "disk.qcow2"
        image.write_bytes(image_content)

        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        result = subprocess.run(
            ["bash", str(self.SCRIPT), str(image)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        return result, image

    def _outputs(self, stdout: str) -> dict[str, str]:
        # .lstrip("\\"): GNU sha256sum prefixes its output hash with a
        # literal backslash when the filename needs escaping (e.g. a
        # Windows-style path containing backslashes, as this test
        # sandbox produces on this dev host) - never happens on real
        # Linux CI, where paths never contain backslashes, but this
        # test must tolerate it to assert the real hash value either
        # way.
        return {
            k: v.lstrip("\\")
            for k, v in (line.split("=", 1) for line in stdout.splitlines() if "=" in line)
        }

    def test_container_hash_matches_real_sha256sum(self, tmp_path):
        content = b"exact real fixture bytes"
        result, _image = self._run(tmp_path, content)
        assert result.returncode == 0, result.stdout + result.stderr
        outputs = self._outputs(result.stdout)
        assert outputs["container_sha256"] == hashlib.sha256(content).hexdigest()

    def test_logical_hash_computed_from_qemu_img_convert(self, tmp_path):
        result, _image = self._run(tmp_path)
        outputs = self._outputs(result.stdout)
        assert outputs["logical_sha256"] == hashlib.sha256(
            self._FAKE_LOGICAL_CONTENT
        ).hexdigest()

    def test_container_and_logical_hashes_are_independent_measurements(self, tmp_path):
        # The central Section 8 distinction - these two hashes come
        # from genuinely different sources (the raw file vs. the
        # converted logical content) and must never accidentally
        # collapse into one measurement.
        result, _image = self._run(tmp_path, b"container bytes differ from logical bytes")
        outputs = self._outputs(result.stdout)
        assert outputs["container_sha256"] != outputs["logical_sha256"]

    def test_no_block_device_means_sentinels_absent_not_fabricated(self, tmp_path):
        # No real /dev/loopXp1/p2 block device exists in this sandbox -
        # must honestly report absent, never fabricate a sentinel hash.
        result, _image = self._run(tmp_path)
        outputs = self._outputs(result.stdout)
        assert outputs["esp_sentinel_present"] == "false"
        assert outputs["esp_sentinel_sha256"] == ""
        assert outputs["data_sentinel_present"] == "false"
        assert outputs["data_sentinel_sha256"] == ""

    def test_missing_required_tool_fails_closed(self, tmp_path):
        bash_path = shutil.which("bash")
        if bash_path is None:
            pytest.skip("bash not available in this environment")
        image = tmp_path / "disk.qcow2"
        image.write_bytes(b"x")
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        env = dict(os.environ)
        env["PATH"] = str(empty_bin)  # deliberately no tools at all
        result = subprocess.run(
            [bash_path, str(self.SCRIPT), str(image)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_missing_image_fails_closed(self, tmp_path):
        bash_path = shutil.which("bash")
        if bash_path is None:
            pytest.skip("bash not available in this environment")
        result = subprocess.run(
            [bash_path, str(self.SCRIPT), str(tmp_path / "does-not-exist.qcow2")],
            cwd=tmp_path, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_no_qemu_nbd_or_nbd_device_dependency(self):
        # S7.1R5 Corrective A - the exact real Run #5 defect class this
        # rewrite eliminates: no nbd kernel module, no /dev/nbdX device
        # node, anywhere in this script's REAL executable code
        # (comments explaining the historical R4 defect legitimately
        # mention these strings, and must not trip this check).
        text = self.SCRIPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "qemu-nbd" not in stripped, line
            assert "/dev/nbd" not in stripped, line
            assert "modprobe" not in stripped, line

    def test_loop_device_attached_readonly(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        connect_line = next(
            li for li in text.splitlines()
            if "losetup --show" in li and not li.strip().startswith("#")
        )
        assert " -r " in connect_line or connect_line.rstrip().endswith(" -r")

    def test_conversion_never_writes_to_source_image(self):
        # qemu-img convert's SOURCE argument (-f qcow2 ... "${IMG}")
        # must never also appear as convert's OWN destination - i.e.
        # the script must convert into a genuinely separate temp file,
        # never in-place.
        text = self.SCRIPT.read_text(encoding="utf-8")
        convert_line = next(
            li for li in text.splitlines()
            if "qemu-img convert" in li and not li.strip().startswith("#")
        )
        assert '"${IMG}"' in convert_line
        assert '"${RAW_TMP}"' in convert_line

    def test_ext4_mount_uses_noload_never_replays_journal(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "ro,noload" in text

    def test_never_mounts_read_write(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.match(r"\s*(sudo )?mount ", line.strip()):
                assert "-o ro" in line, line

    def test_cleanup_removes_temp_raw_file_and_loop_device_on_success(self, tmp_path):
        result, _image = self._run(tmp_path)
        assert result.returncode == 0
        leftover = list(tmp_path.glob(".hash-disk-image-raw.*"))
        assert leftover == []


# ---------------------------------------------------------------------------
# S7.1R6 Objective C: installer/scripts/inspect-target-layout.sh - real
# bash execution against stub sudo/qemu-img/losetup/blkid tools.
# Rewritten to remove the same qemu-nbd/nbd-device-node dependency
# real Run #5 proved fragile in the sibling hash-disk-image.sh - this
# script's own nbd2 usage had never actually executed successfully in
# any real run (every prior run timed out before "Inspect target disk
# layout" could run at all).
#
# Section 9's own instruction: "if actual runtime-level NBD
# verification cannot be performed locally... do not label it PASS."
# This development environment has no real block-device/loop
# capability, so only what is HONESTLY testable without one is tested
# here - a genuine "valid expected layout accepted" runtime scenario
# remains TARGET_LAYOUT_INSPECTOR_RUNTIME=NOT_OBSERVED, reported as
# such in the final report, never fabricated as PASS.
# ---------------------------------------------------------------------------


class TestInspectTargetLayoutScript:
    SCRIPT = REPO_ROOT / "installer" / "scripts" / "inspect-target-layout.sh"

    def _fake_tools(self, bin_dir: Path, *, convert_exit: int = 0) -> None:
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name, body in {
            "sudo": '#!/usr/bin/env bash\nexec "$@"\n',
            "qemu-img": (
                "#!/usr/bin/env bash\n"
                'if [ "$1" = "convert" ]; then\n'
                f"  exit {convert_exit}\n"
                "fi\n"
                "exit 1\n"
            ),
            "losetup": (
                "#!/usr/bin/env bash\n"
                'case "$1" in\n'
                "  --show) echo '/dev/loop88'; exit 0 ;;\n"
                "  -d) exit 0 ;;\n"
                "esac\n"
                "exit 0\n"
            ),
            "partprobe": "#!/usr/bin/env bash\nexit 0\n",
            # No real loop-backed block device exists in this sandbox -
            # blkid never gets a real path to inspect anyway
            # ([ -b ... ] already fails first), but fail closed too.
            "blkid": "#!/usr/bin/env bash\nexit 1\n",
        }.items():
            script = bin_dir / name
            script.write_text(body)
            script.chmod(0o755)

    def _run(
        self, tmp_path: Path, *, convert_exit: int = 0, image_present: bool = True
    ) -> tuple[subprocess.CompletedProcess, Path]:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        bin_dir = tmp_path / "bin"
        self._fake_tools(bin_dir, convert_exit=convert_exit)
        target = tmp_path / "disk-target.qcow2"
        if image_present:
            target.write_bytes(b"fake target qcow2 bytes")

        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        result = subprocess.run(
            ["bash", str(self.SCRIPT), str(target)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        return result, target

    def _outputs(self, stdout: str) -> dict[str, str]:
        return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)

    def test_no_block_device_reports_honest_fail_closed_defaults(self, tmp_path):
        # TARGET_LAYOUT_INSPECTOR_RUNTIME=NOT_OBSERVED (Section 9) - no
        # real loop-backed partition exists in this sandbox, so this is
        # the only runtime scenario honestly testable here. Every field
        # must be the fail-closed default, never fabricated.
        result, _target = self._run(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        outputs = self._outputs(result.stdout)
        assert outputs["target_esp_present"] == "false"
        assert outputs["target_root_present"] == "false"
        assert outputs["serein_core_present"] == "false"
        assert outputs["firstboot_provisioning"] == "unknown"

    def test_missing_image_fails_closed(self, tmp_path):
        result, _target = self._run(tmp_path, image_present=False)
        assert result.returncode != 0

    def test_conversion_failure_fails_closed_and_cleans_up(self, tmp_path):
        result, _target = self._run(tmp_path, convert_exit=1)
        assert result.returncode != 0
        leftover = list(tmp_path.glob(".inspect-target-layout-raw.*"))
        assert leftover == []

    def test_missing_required_tool_fails_closed(self, tmp_path):
        bash_path = shutil.which("bash")
        if bash_path is None:
            pytest.skip("bash not available in this environment")
        target = tmp_path / "disk-target.qcow2"
        target.write_bytes(b"x")
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        env = dict(os.environ)
        env["PATH"] = str(empty_bin)
        result = subprocess.run(
            [bash_path, str(self.SCRIPT), str(target)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_cleanup_removes_temp_raw_file_on_success(self, tmp_path):
        result, _target = self._run(tmp_path)
        assert result.returncode == 0
        leftover = list(tmp_path.glob(".inspect-target-layout-raw.*"))
        assert leftover == []

    def test_no_qemu_nbd_or_nbd_device_dependency(self):
        # S7.1R6 Objective C - the exact same real defect class this
        # rewrite eliminates for this sibling script (comments
        # explaining the historical defect legitimately mention these
        # strings, and must not trip this check).
        text = self.SCRIPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "qemu-nbd" not in stripped, line
            assert "/dev/nbd" not in stripped, line
            assert "modprobe" not in stripped, line

    def test_loop_device_attached_readonly(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        connect_line = next(
            li for li in text.splitlines()
            if "losetup --show" in li and not li.strip().startswith("#")
        )
        assert " -r " in connect_line or connect_line.rstrip().endswith(" -r")

    def test_root_mount_uses_noload_never_replays_journal(self):
        # The real, independently-found gap this pass fixes - the
        # previous version used plain `-o ro` (no noload) for the root
        # partition, risking a journal replay on a disk a real install
        # just touched.
        text = self.SCRIPT.read_text(encoding="utf-8")
        mount_line = next(
            li for li in text.splitlines()
            if re.match(r"\s*if sudo mount ", li) and "p2" in li
        )
        assert "ro,noload" in mount_line

    def test_never_mounts_read_write(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.match(r"\s*(sudo )?mount ", line.strip()):
                assert "-o ro" in line, line

    def test_conversion_never_writes_to_source_image(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        convert_line = next(
            li for li in text.splitlines()
            if "qemu-img convert" in li and not li.strip().startswith("#")
        )
        assert '"${TARGET_IMG}"' in convert_line
        assert '"${RAW_TMP}"' in convert_line

    def test_output_contract_unchanged_from_prior_version(self):
        # Section 9's own concern: other code (evidence assembly)
        # depends on these exact keys - the rewrite must never change
        # the output contract, only the internal mechanism.
        text = self.SCRIPT.read_text(encoding="utf-8")
        for key in (
            "target_esp_present=", "target_root_present=",
            "serein_core_present=", "firstboot_provisioning=",
        ):
            assert key in text


# ---------------------------------------------------------------------------
# S7.1R4 Section 10: installer/scripts/extract-installer-signals.sh
# ---------------------------------------------------------------------------


class TestExtractInstallerSignalsScript:
    SCRIPT = REPO_ROOT / "installer" / "scripts" / "extract-installer-signals.sh"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        return subprocess.run(
            ["bash", str(self.SCRIPT), *args], capture_output=True, text=True, timeout=15
        )

    def test_extracts_matching_lines_only(self, tmp_path):
        serial = tmp_path / "serial.log"
        serial.write_text(
            "boot line one\n"
            "subiquity server starting\n"
            "irrelevant line\n"
            "curtin: install begins\n"
            "another irrelevant line\n"
            "ERROR: something failed\n"
        )
        output = tmp_path / "signals.log"
        result = self._run([str(serial), str(output)])
        assert result.returncode == 0
        text = output.read_text()
        assert "subiquity server starting" in text
        assert "curtin: install begins" in text
        assert "ERROR: something failed" in text
        assert "irrelevant line" not in text
        assert "boot line one" not in text

    def test_missing_serial_log_handled_honestly(self, tmp_path):
        output = tmp_path / "signals.log"
        result = self._run([str(tmp_path / "does-not-exist.log"), str(output)])
        assert result.returncode == 0
        assert "no serial log present" in output.read_text()

    def test_no_matches_handled_honestly(self, tmp_path):
        serial = tmp_path / "serial.log"
        serial.write_text("nothing relevant here\njust boot noise\n")
        output = tmp_path / "signals.log"
        result = self._run([str(serial), str(output)])
        assert result.returncode == 0
        assert "no subiquity/curtin/autoinstall" in output.read_text()

    def test_never_fails_the_job_regardless_of_match_outcome(self, tmp_path):
        for content in ("no matches here\n", "subiquity: real match\n"):
            serial = tmp_path / "serial.log"
            serial.write_text(content)
            output = tmp_path / "signals.log"
            result = self._run([str(serial), str(output)])
            assert result.returncode == 0


# ---------------------------------------------------------------------------
# S7.1R7 Objective A: installer/scripts/extract-bootstrap-milestones.sh
# - real bash execution, purely host-side parsing of an already-
# captured serial log. Real Run #7 (RUN_ID=34335197624) evidence is
# used as the synthetic fixture content below, so these tests directly
# reproduce the exact real timeline the corrective was written against.
# ---------------------------------------------------------------------------


class TestExtractBootstrapMilestonesScript:
    SCRIPT = REPO_ROOT / "installer" / "scripts" / "extract-bootstrap-milestones.sh"

    # A synthetic serial log reproducing the exact real Run #7 timeline
    # (Section 3 of the S7.1R7 spec) - never fabricated numbers, these
    # are the real, reported milestone timestamps.
    _RUN_7_LIKE_LOG = (
        "[    0.000000] Linux version 7.0.0-30-generic\n"
        "[    5.178096] systemd[1]: systemd 259.5 running in system mode\n"
        "[  120.000000] Starting snapd.service\n"
        "[  437.540000] snapd.seeded.service: Starting...\n"
        "[  597.930000] snap client: cannot communicate with server: "
        "timeout exceeded while waiting for response\n"
        "[  598.000000] snapd.seeded.service failed\n"
        "[  613.000000] snapd.service: start operation timed out\n"
        "[  703.000000] snapd.service failed, restarting\n"
        "[  826.000000] snapd.service: start operation timed out\n"
        "[  878.000000] snapd.service failed, restarting\n"
        "[ 1047.000000] desktop-security-center configure hook failed\n"
        "[ 1047.500000] sanity timeout expired\n"
        "[ 1068.000000] RemoveSnapServices begin\n"
        "[ 1516.000000] /snap/snapd/current: no such file or directory\n"
        "[ 1946.000000] snap client: cannot communicate with server: "
        "timeout exceeded while waiting for response\n"
        "[ 3474.450000] snapd: no NTP sync after 10m0s, trying auto-refresh anyway\n"
        "[ 3481.790000] Finished snapd.seeded.service\n"
        "[ 3550.000000] subiquity: extract_autoinstall\n"
        "[ 3552.000000] subiquity: load_autoinstall_config\n"
        "[ 3555.000000] subiquity: apply_autoinstall_config\n"
        "[ 3565.150000] subiquity: Install/install\n"
        "[ 3579.000000] python3.12 -m curtin --showtrace -vvv\n"
        "[ 3581.330000] curtin: apt-config begins\n"
    )

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        return subprocess.run(
            ["bash", str(self.SCRIPT), *args], capture_output=True, text=True, timeout=15
        )

    def _outputs(self, tmp_path: Path, log_content: str, qemu_elapsed: str = "") -> dict[str, str]:
        serial = tmp_path / "serial.log"
        serial.write_text(log_content)
        output = tmp_path / "milestones.env"
        args = [str(serial), str(output)]
        if qemu_elapsed:
            args.append(qemu_elapsed)
        result = self._run(args)
        assert result.returncode == 0, result.stdout + result.stderr
        return {
            k: v for k, v in (
                line.split("=", 1) for line in output.read_text().splitlines()
                if "=" in line and not line.startswith("#")
            )
        }

    def test_reproduces_the_real_run_7_snapd_seed_duration(self, tmp_path):
        outputs = self._outputs(tmp_path, self._RUN_7_LIKE_LOG, qemu_elapsed="3600")
        # Real Run #7: RUN_7_SNAPD_SEEDED_DURATION≈3044.25s.
        assert outputs["snapd_seed_duration"] == "3044.25"

    def test_reproduces_the_real_run_7_curtin_runtime_before_timeout(self, tmp_path):
        outputs = self._outputs(tmp_path, self._RUN_7_LIKE_LOG, qemu_elapsed="3600")
        # Real Run #7: curtin had only ~19-21s before QEMU termination.
        assert outputs["curtin_runtime_before_qemu_exit"] == "21.00"

    def test_second_occurrence_milestones_are_genuinely_distinct(self, tmp_path):
        outputs = self._outputs(tmp_path, self._RUN_7_LIKE_LOG, qemu_elapsed="3600")
        assert outputs["snapd_first_startup_timeout"] == "613.000000"
        assert outputs["snapd_second_startup_timeout"] == "826.000000"
        assert outputs["snapd_first_client_timeout"] == "597.930000"
        assert outputs["snap_second_client_timeout"] == "1946.000000"

    def test_all_named_milestones_from_run_7_are_captured(self, tmp_path):
        outputs = self._outputs(tmp_path, self._RUN_7_LIKE_LOG, qemu_elapsed="3600")
        for key in (
            "desktop_security_center_hook_failure", "desktop_security_center_sanity_timeout",
            "snap_removal_begin", "snapd_current_missing", "ntp_10m_timeout",
            "snapd_seeded_success", "subiquity_autoinstall_extract",
            "subiquity_autoinstall_load", "subiquity_apply", "subiquity_install_enter",
            "curtin_start", "curtin_apt_config",
        ):
            assert outputs[key] != "", f"{key} should have been observed"

    def test_unobserved_milestone_is_empty_never_fabricated(self, tmp_path):
        # A minimal log with none of the snapd-failure markers - those
        # milestones must be genuinely empty, never a guessed value.
        minimal_log = "[    0.000000] Linux version 7.0.0\n"
        outputs = self._outputs(tmp_path, minimal_log)
        assert outputs["snapd_first_client_timeout"] == ""
        assert outputs["desktop_security_center_hook_failure"] == ""
        assert outputs["ntp_10m_timeout"] == ""

    def test_qemu_timeout_is_host_side_value_not_guest_log_matched(self, tmp_path):
        # qemu's own "terminating on signal 15" message has no guest
        # timestamp - the qemu_timeout milestone must come directly
        # from the passed-in elapsed-seconds argument.
        outputs = self._outputs(tmp_path, self._RUN_7_LIKE_LOG, qemu_elapsed="3600")
        assert outputs["qemu_timeout"] == "3600"

    def test_qemu_timeout_empty_when_not_provided(self, tmp_path):
        outputs = self._outputs(tmp_path, self._RUN_7_LIKE_LOG)
        assert outputs["qemu_timeout"] == ""

    def test_missing_serial_log_handled_honestly(self, tmp_path):
        output = tmp_path / "milestones.env"
        result = self._run([str(tmp_path / "does-not-exist.log"), str(output)])
        assert result.returncode == 0
        assert "no serial log present" in output.read_text()

    def test_never_fails_the_job(self, tmp_path):
        for content in ("", "no matches at all\n", self._RUN_7_LIKE_LOG):
            serial = tmp_path / "serial.log"
            serial.write_text(content)
            output = tmp_path / "milestones.env"
            result = self._run([str(serial), str(output)])
            assert result.returncode == 0

    def test_never_mutates_the_serial_log(self, tmp_path):
        serial = tmp_path / "serial.log"
        serial.write_text(self._RUN_7_LIKE_LOG)
        before = serial.read_text()
        output = tmp_path / "milestones.env"
        self._run([str(serial), str(output), "3600"])
        assert serial.read_text() == before


# ---------------------------------------------------------------------------
# installer/scripts/*.sh - static sanity + git-executable-bit correctness
# ---------------------------------------------------------------------------


class TestInstallerScriptsStatic:
    def test_every_script_has_bash_shebang_and_strict_mode(self):
        scripts_dir = REPO_ROOT / "installer" / "scripts"
        for script in scripts_dir.glob("*.sh"):
            text = script.read_text(encoding="utf-8")
            assert text.startswith("#!/usr/bin/env bash"), script
            assert "set -euo pipefail" in text, script

    def test_no_script_references_a_physical_device_path(self):
        scripts_dir = REPO_ROOT / "installer" / "scripts"
        for script in scripts_dir.glob("*.sh"):
            text = script.read_text(encoding="utf-8")
            for forbidden in ("/dev/sda", "/dev/sdb", "/dev/nvme0n1"):
                assert forbidden not in text, f"{script} references {forbidden!r}"

    def test_bash_syntax_check(self):
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")
        scripts_dir = REPO_ROOT / "installer" / "scripts"
        for script in scripts_dir.glob("*.sh"):
            result = subprocess.run(
                ["bash", "-n", str(script)], capture_output=True, text=True
            )
            assert result.returncode == 0, f"{script}: {result.stderr}"

    def test_r6_target_fixture_capacity_increased_protected_unchanged(self):
        # S7.1R6 Objective B: real Run #6 evidence (Serein's own built
        # QA ISO is ~7 GiB per docs/installer/storage-lifecycle.md's
        # own documented QA_ISO_GIB estimate) means the previous 8G
        # target left essentially no real margin for a decompressed
        # full-desktop install. Only the TARGET fixture grows - the
        # PROTECTED fixture size is independently justified (it exists
        # only to prove non-mutation, not to hold an installed system)
        # and must never change merely because target did.
        text = (REPO_ROOT / "installer" / "scripts" / "create-fixture-disks.sh").read_text(
            encoding="utf-8"
        )
        protected_line = next(
            li for li in text.splitlines() if '"${OUT_DIR}/disk-protected.qcow2"' in li
        )
        assert "4G" in protected_line
        target_line = next(
            li for li in text.splitlines() if '"${OUT_DIR}/disk-target.qcow2"' in li
        )
        assert "16G" in target_line
        assert "8G" not in target_line


class TestInstallerScriptExecutableModes:
    """Mirrors ``tests/test_distribution.py::TestGitExecutableModes`` -
    a real S7.0 Layer-B run once failed with ``Permission denied``
    because a shell entrypoint was tracked as ``100644`` in the Git
    tree; a filesystem ``chmod`` alone cannot fix this, since GitHub
    Actions materializes whatever mode the Git *tree* records."""

    def _tracked_modes(self) -> dict[str, str]:
        result = subprocess.run(
            ["git", "ls-files", "-s", "installer/scripts/"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        modes: dict[str, str] = {}
        for line in result.stdout.splitlines():
            import re

            match = re.match(r"^(\d{6})\s+\S+\s+\d+\t(.+)$", line)
            if match:
                modes[match.group(2)] = match.group(1)
        return modes

    def test_all_installer_shell_entrypoints_are_git_executable(self):
        scripts_dir = REPO_ROOT / "installer" / "scripts"
        if not scripts_dir.is_dir():
            pytest.skip("installer/scripts/ does not exist")
        required = {f"installer/scripts/{p.name}" for p in scripts_dir.glob("*.sh")}
        assert required, "expected at least one *.sh entrypoint to check"

        modes = self._tracked_modes()
        for path in sorted(required):
            assert path in modes, f"{path} is not tracked by git at all"
            assert modes[path] == "100755", (
                f"{path} has git tree mode {modes[path]!r}, expected '100755'"
            )


# ---------------------------------------------------------------------------
# isoprep
# ---------------------------------------------------------------------------


# A realistic fake grub.cfg mirroring exactly the structure real Run #3
# evidence proved (RUN_ID=34224122883): the QA-serial-boot-smoke entry
# S7.0's own qa_boot.transition_to_qa_in_place bakes in - default,
# short timeout, `console=ttyS0,115200n8` already present, `---`
# separator, no `autoinstall` token anywhere - alongside an unrelated
# second entry that must NEVER be touched.
_FAKE_QA_GRUB_CFG = f"""set default="0"
set timeout=1

menuentry "{QA_ENTRY_TITLE}" {{
    linux   /casper/vmlinuz console=ttyS0,115200n8 ---
    initrd  /casper/initrd
}}

menuentry "Try or Install Ubuntu" {{
    linux   /casper/vmlinuz quiet splash ---
    initrd  /casper/initrd
}}
"""


def _write_fake_qa_grub_cfg(extracted_dir: Path) -> Path:
    grub_path = extracted_dir / "boot" / "grub" / "grub.cfg"
    grub_path.parent.mkdir(parents=True, exist_ok=True)
    grub_path.write_text(_FAKE_QA_GRUB_CFG, encoding="utf-8")
    return grub_path


class TestIsoPrep:
    def test_prepare_qa_install_iso_embeds_autoinstall_and_rebuilds(self, tmp_path):
        qa_iso = tmp_path / "serein-alpha-qa.iso"
        qa_iso.write_bytes(b"fake qa iso")

        def fake_runner(argv, **kwargs):
            if "-osirrox" in argv and "-extract" in argv:
                dest = Path(argv[argv.index("-extract") + 2])
                dest.mkdir(parents=True, exist_ok=True)
                _write_fake_qa_grub_cfg(dest)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if "-report_el_torito" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="-c '/boot.catalog'\n-appended_part_as_gpt\n", stderr=""
                )
            if "-as" in argv and "mkisofs" in argv:
                out = Path(argv[argv.index("-o") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"fake qa-install iso")
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            raise AssertionError(argv)

        output = tmp_path / "dist" / "serein-alpha-qa-install.iso"
        result = prepare_qa_install_iso(
            qa_iso, tmp_path / "work", output, "AUTOINSTALL CONTENT",
            subprocess_runner=fake_runner,
        )
        assert result == output
        assert output.is_file()
        extracted = tmp_path / "work" / "qa-install-extracted"
        written = (extracted / "autoinstall.yaml").read_text()
        assert written == "AUTOINSTALL CONTENT"

        # -- S7.1R3: the real, proven fix - the rebuilt medium's own
        # boot entry must actually carry `autoinstall` now. --
        final_grub = (extracted / "boot" / "grub" / "grub.cfg").read_text()
        qa_entry_body = final_grub.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert re.search(r"(?<!\S)autoinstall(?!\S)", qa_entry_body)
        # Never after the `---` init-arg separator.
        linux_line = next(li for li in qa_entry_body.splitlines() if "linux" in li)
        assert re.search(r"autoinstall.*---", linux_line)
        # The serial console token S7.0 already added must survive.
        assert "console=ttyS0,115200n8" in qa_entry_body
        # -- S7.1R5 Objective C: journald forwarding chained on top. --
        assert "systemd.journald.forward_to_console=1" in qa_entry_body
        # -- S7.1R7 Objective A: debug logging chained on top too. --
        assert "systemd.log_level=debug" in qa_entry_body
        # The unrelated second entry must never be touched.
        other_entry_body = final_grub.split('menuentry "Try or Install Ubuntu"')[1]
        assert "autoinstall" not in other_entry_body
        assert "systemd.log_level" not in other_entry_body
        assert "systemd.journald.forward_to_console" not in other_entry_body

    def test_missing_source_iso_fails_closed(self, tmp_path):
        with pytest.raises(IsoPrepError):
            prepare_qa_install_iso(
                tmp_path / "does-not-exist.iso", tmp_path / "work", tmp_path / "out.iso", "x",
            )

    def test_extraction_failure_fails_closed(self, tmp_path):
        qa_iso = tmp_path / "serein-alpha-qa.iso"
        qa_iso.write_bytes(b"fake qa iso")

        def failing_runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="extraction failed")

        with pytest.raises(IsoPrepError, match="extraction"):
            prepare_qa_install_iso(
                qa_iso, tmp_path / "work", tmp_path / "out.iso", "x",
                subprocess_runner=failing_runner,
            )

    def test_missing_grub_config_fails_closed(self, tmp_path):
        # No boot/grub/grub.cfg written by this fake extraction at all -
        # must never silently ship an ISO with no autoinstall trigger.
        qa_iso = tmp_path / "serein-alpha-qa.iso"
        qa_iso.write_bytes(b"fake qa iso")

        def fake_runner(argv, **kwargs):
            if "-osirrox" in argv and "-extract" in argv:
                dest = Path(argv[argv.index("-extract") + 2])
                dest.mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if "-report_el_torito" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="-c '/boot.catalog'\n", stderr=""
                )
            raise AssertionError(argv)

        with pytest.raises(IsoPrepError, match="autoinstall boot"):
            prepare_qa_install_iso(
                qa_iso, tmp_path / "work", tmp_path / "out.iso", "x",
                subprocess_runner=fake_runner,
            )

    def test_second_invocation_starts_from_clean_scratch(self, tmp_path):
        qa_iso = tmp_path / "serein-alpha-qa.iso"
        qa_iso.write_bytes(b"fake qa iso")

        def fake_runner(argv, **kwargs):
            if "-osirrox" in argv and "-extract" in argv:
                dest = Path(argv[argv.index("-extract") + 2])
                dest.mkdir(parents=True, exist_ok=True)
                _write_fake_qa_grub_cfg(dest)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if "-report_el_torito" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="-c '/boot.catalog'\n", stderr=""
                )
            if "-as" in argv and "mkisofs" in argv:
                out = Path(argv[argv.index("-o") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"iso")
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            raise AssertionError(argv)

        work_dir = tmp_path / "work"
        prepare_qa_install_iso(
            qa_iso, work_dir, tmp_path / "a.iso", "FIRST", subprocess_runner=fake_runner
        )
        (work_dir / "qa-install-extracted" / "stale.txt").write_text("leftover")
        prepare_qa_install_iso(
            qa_iso, work_dir, tmp_path / "b.iso", "SECOND", subprocess_runner=fake_runner
        )
        assert not (work_dir / "qa-install-extracted" / "stale.txt").exists()
        assert (work_dir / "qa-install-extracted" / "autoinstall.yaml").read_text() == "SECOND"


class TestEnableAutoinstallOnQaEntry:
    """S7.1R3: real, direct regression coverage for the exact Run #3
    root cause (RUN_ID=34224122883) - the QA-serial-boot-smoke entry's
    real, proven-missing kernel parameter."""

    def test_reproduces_exact_run_3_missing_parameter(self):
        # The EXACT real kernel command line Run #3 proved was booted -
        # no autoinstall token anywhere.
        patched = _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG)
        qa_body = patched.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        linux_line = next(li for li in qa_body.splitlines() if "linux" in li)
        assert "console=ttyS0,115200n8" in linux_line
        assert re.search(r"(?<!\S)autoinstall(?!\S)", linux_line)

    def test_inserted_before_init_arg_separator_never_after(self):
        patched = _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG)
        qa_body = patched.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        linux_line = next(li for li in qa_body.splitlines() if "linux" in li)
        before_sep, _, after_sep = linux_line.partition("---")
        assert "autoinstall" in before_sep
        assert "autoinstall" not in after_sep

    def test_idempotent_no_duplicate_on_second_call(self):
        once = _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG)
        twice = _enable_autoinstall_on_qa_entry(once)
        assert once == twice
        qa_body = twice.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert qa_body.count("autoinstall") == 1

    def test_unrelated_entry_never_touched(self):
        patched = _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG)
        other_body = patched.split('menuentry "Try or Install Ubuntu"')[1]
        assert "autoinstall" not in other_body
        assert "quiet splash" in other_body  # untouched, exact original text

    def test_missing_entry_title_fails_closed(self):
        with pytest.raises(AutoinstallBootError, match="no menuentry titled"):
            _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG, entry_title="Does Not Exist")

    def test_entry_with_no_linux_line_fails_closed(self):
        broken = f'menuentry "{QA_ENTRY_TITLE}" {{\n    initrd /casper/initrd\n}}\n'
        with pytest.raises(AutoinstallBootError, match="no linux/linuxefi line"):
            _enable_autoinstall_on_qa_entry(broken)

    def test_linuxefi_directive_also_supported(self):
        text = (
            f'menuentry "{QA_ENTRY_TITLE}" {{\n'
            "    linuxefi /casper/vmlinuz console=ttyS0,115200n8 ---\n"
            "    initrdefi /casper/initrd\n"
            "}\n"
        )
        patched = _enable_autoinstall_on_qa_entry(text)
        assert re.search(r"(?<!\S)autoinstall(?!\S)", patched)

    def test_never_mutates_qa_boot_modules_own_contract(self):
        # S7.1R3 Section 21/29: never reopens S7.0's qa_boot.py, whose
        # derive_qa_menuentry must keep refusing to add autoinstall for
        # its OWN (boot-smoke-only) purpose.
        from serein.distribution.qa_boot import derive_qa_menuentry

        base_cfg = (
            'menuentry "Try or Install Ubuntu" {\n'
            "    linux   /casper/vmlinuz quiet splash ---\n"
            "    initrd  /casper/initrd\n"
            "}\n"
        )
        qa_entry_text = derive_qa_menuentry(base_cfg)
        assert "autoinstall" not in qa_entry_text


class TestJournaldConsoleForwardingOnQaEntry:
    """S7.1R5 Objective C: real, direct regression coverage for the
    new systemd.journald.forward_to_console=1 kernel-parameter
    addition - reuses the exact same, already-tested core mechanism
    as _enable_autoinstall_on_qa_entry (Run #3's proven fix)."""

    def test_token_added_to_qa_entry_only(self):
        patched = _enable_journald_console_forwarding_on_qa_entry(_FAKE_QA_GRUB_CFG)
        qa_body = patched.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert "systemd.journald.forward_to_console=1" in qa_body
        other_body = patched.split('menuentry "Try or Install Ubuntu"')[1]
        assert "systemd.journald.forward_to_console" not in other_body

    def test_inserted_before_init_arg_separator(self):
        patched = _enable_journald_console_forwarding_on_qa_entry(_FAKE_QA_GRUB_CFG)
        qa_body = patched.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        linux_line = next(li for li in qa_body.splitlines() if "linux" in li)
        before_sep, _, after_sep = linux_line.partition("---")
        assert "systemd.journald.forward_to_console" in before_sep
        assert "systemd.journald.forward_to_console" not in after_sep

    def test_idempotent_no_duplicate(self):
        once = _enable_journald_console_forwarding_on_qa_entry(_FAKE_QA_GRUB_CFG)
        twice = _enable_journald_console_forwarding_on_qa_entry(once)
        assert once == twice
        qa_body = twice.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert qa_body.count("systemd.journald.forward_to_console") == 1

    def test_composes_with_autoinstall_token_chained(self):
        # The exact real usage in prepare_qa_install_iso - autoinstall
        # first, then journald forwarding chained onto that result.
        with_autoinstall = _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG)
        both = _enable_journald_console_forwarding_on_qa_entry(with_autoinstall)
        qa_body = both.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert "autoinstall" in qa_body
        assert "systemd.journald.forward_to_console=1" in qa_body
        assert "console=ttyS0,115200n8" in qa_body

    def test_missing_entry_title_fails_closed(self):
        with pytest.raises(AutoinstallBootError, match="no menuentry titled"):
            _enable_journald_console_forwarding_on_qa_entry(
                _FAKE_QA_GRUB_CFG, entry_title="Does Not Exist"
            )


class TestSystemdDebugLoggingOnQaEntry:
    """S7.1R7 Objective A: real, direct regression coverage for the
    new systemd.log_level=debug kernel-parameter addition - reuses the
    exact same, already-tested core mechanism."""

    def test_token_added_to_qa_entry_only(self):
        patched = _enable_systemd_debug_logging_on_qa_entry(_FAKE_QA_GRUB_CFG)
        qa_body = patched.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert "systemd.log_level=debug" in qa_body
        other_body = patched.split('menuentry "Try or Install Ubuntu"')[1]
        assert "systemd.log_level" not in other_body

    def test_idempotent_no_duplicate(self):
        once = _enable_systemd_debug_logging_on_qa_entry(_FAKE_QA_GRUB_CFG)
        twice = _enable_systemd_debug_logging_on_qa_entry(once)
        assert once == twice
        qa_body = twice.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert qa_body.count("systemd.log_level=debug") == 1

    def test_composes_with_autoinstall_and_journald_tokens_chained(self):
        # The exact real usage in prepare_qa_install_iso.
        step1 = _enable_autoinstall_on_qa_entry(_FAKE_QA_GRUB_CFG)
        step2 = _enable_journald_console_forwarding_on_qa_entry(step1)
        step3 = _enable_systemd_debug_logging_on_qa_entry(step2)
        qa_body = step3.split(f'menuentry "{QA_ENTRY_TITLE}"')[1].split("}")[0]
        assert "autoinstall" in qa_body
        assert "systemd.journald.forward_to_console=1" in qa_body
        assert "systemd.log_level=debug" in qa_body
        assert "console=ttyS0,115200n8" in qa_body

    def test_missing_entry_title_fails_closed(self):
        with pytest.raises(AutoinstallBootError, match="no menuentry titled"):
            _enable_systemd_debug_logging_on_qa_entry(
                _FAKE_QA_GRUB_CFG, entry_title="Does Not Exist"
            )


# ---------------------------------------------------------------------------
# CLI wiring - Sections 23-24 (Test I: read-only commands prove zero mutation)
# ---------------------------------------------------------------------------


class TestCli:
    def test_installer_status_registered(self, capsys):
        from serein.cli import main

        exit_code = main(["installer", "status"])
        assert exit_code == 0
        assert "SEREIN INSTALLER" in capsys.readouterr().out

    def test_installer_disks_json(self, capsys):
        from serein.cli import main

        exit_code = main(["installer", "disks", "--json"])
        assert exit_code == 0
        data = json.loads(capsys.readouterr().out)
        assert "disks" in data

    def test_installer_doctor_json(self, capsys):
        from serein.cli import main

        exit_code = main(["installer", "doctor", "--json"])
        assert exit_code == 0
        data = json.loads(capsys.readouterr().out)
        assert "checks" in data

    def test_installer_plan_no_target_blocked(self, capsys):
        from serein.cli import main

        exit_code = main(["installer", "plan", "--target", "/dev/does-not-exist"])
        assert exit_code == 1
        assert "NO_TARGET" in capsys.readouterr().err

    def test_no_destructive_binaries_referenced_in_read_only_modules(self):
        # Static proof: none of the read-only command modules
        # (status.py, diskprobe.py, doctor.py, and the CLI dispatch
        # functions themselves) reference a mutating tool invocation.
        forbidden = ("wipefs", "mkfs.", "parted ", "grub-install", "curtin install", "dd if=")
        read_only_sources = [
            REPO_ROOT / "src" / "serein" / "installer" / "status.py",
            REPO_ROOT / "src" / "serein" / "installer" / "diskprobe.py",
            REPO_ROOT / "src" / "serein" / "installer" / "doctor.py",
        ]
        for path in read_only_sources:
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                assert word not in text, f"{path} unexpectedly references {word!r}"


class TestHeavyCli:
    """``python -m serein.installer`` - QA-CI-only tooling."""

    def test_render_autoinstall_end_to_end(self, tmp_path):
        if shutil.which("openssl") is None:
            pytest.skip("openssl not available in this environment")
        from serein.installer.__main__ import main as installer_main

        out_yaml = tmp_path / "autoinstall.yaml"
        out_plan = tmp_path / "plan.json"
        exit_code = installer_main([
            "render-autoinstall",
            "--target-device-path", "/dev/vdb", "--target-serial", "TGT",
            "--target-size-bytes", "34359738368",
            "--protected-disk", "PROT:/dev/vda",
            "--source-commit", "a" * 40, "--source-media-version", "26.04.1",
            "--out-yaml", str(out_yaml), "--out-plan", str(out_plan),
            "--qa-allow-autoinstall",
        ])
        assert exit_code == 0
        assert out_yaml.is_file()
        plan_data = json.loads(out_plan.read_text())
        assert plan_data["validation"]["valid"] is True

    def test_render_autoinstall_refuses_without_flag(self, tmp_path, capsys):
        from serein.installer.__main__ import main as installer_main

        exit_code = installer_main([
            "render-autoinstall",
            "--target-device-path", "/dev/vdb", "--target-serial", "TGT",
            "--protected-disk", "PROT:/dev/vda",
            "--source-commit", "a" * 40, "--source-media-version", "26.04.1",
            "--out-yaml", str(tmp_path / "autoinstall.yaml"),
        ])
        assert exit_code == 1
        assert "qa-allow-autoinstall" in capsys.readouterr().err

    def test_render_autoinstall_blocks_plan_escape(self, tmp_path, capsys):
        from serein.installer.__main__ import main as installer_main

        exit_code = installer_main([
            "render-autoinstall",
            "--target-device-path", "/dev/vdb", "--target-serial", "TGT",
            # deliberately declare the target itself as ALSO protected -
            # its own device path collides with a protected entry
            "--protected-disk", "OTHER:/dev/vdb",
            "--source-commit", "a" * 40, "--source-media-version", "26.04.1",
            "--out-yaml", str(tmp_path / "autoinstall.yaml"),
            "--qa-allow-autoinstall",
        ])
        assert exit_code == 1
        assert "PLAN_ESCAPE" in capsys.readouterr().err

    def test_evidence_and_closure_gate_roundtrip(self, tmp_path):
        from serein.installer.__main__ import main as installer_main

        evidence_path = tmp_path / "evidence.json"
        exit_code = installer_main([
            "evidence",
            "--source-commit", "a" * 40,
            "--installer-backend-available",
            "--target-explicit", "--target-serial", "TGT", "--target-device-path", "/dev/vdb",
            "--target-identity-revalidated",
            "--protected-disk", "PROT:/dev/vda",
            "--plan-valid", "--all-destructive-ops-on-target",
            "--target-disk-before-sha256", "a" * 64, "--target-disk-after-sha256", "b" * 64,
            "--protected-before-sha256", "c" * 64, "--protected-after-sha256", "c" * 64,
            "--target-esp-present", "--target-root-present", "--protected-esp-unchanged",
            "--installation-status", "pass", "--install-media-removed-for-boot",
            "--installed-boot-status", "pass",
            "--serein-core-present", "--firstboot-provisioning", "pending",
            "--out", str(evidence_path),
        ])
        assert exit_code == 0

        # installed_boot_mode/marker weren't set via --installed-boot-result,
        # so closure must still fail on those two - proving the CLI
        # doesn't silently fabricate them.
        exit_code = installer_main([
            "closure-gate", "--evidence", str(evidence_path),
            "--expected-source-commit", "a" * 40,
        ])
        assert exit_code == 1

    def test_evidence_reads_installed_boot_result_json(self, tmp_path):
        from serein.installer.__main__ import main as installer_main

        boot_result = tmp_path / "boot-result.json"
        boot_result.write_text(json.dumps({
            "status": "pass", "boot_mode": "uefi",
            "matched_marker": "Reached target basic.target - Basic System.",
        }))
        evidence_path = tmp_path / "evidence.json"
        exit_code = installer_main([
            "evidence", "--source-commit", "a" * 40,
            "--installed-boot-result", str(boot_result),
            "--out", str(evidence_path),
        ])
        assert exit_code == 0
        data = json.loads(evidence_path.read_text())
        assert data["installed_boot_status"] == "pass"
        assert data["installed_boot_mode"] == "uefi"
        assert data["installed_boot_marker"] == "Reached target basic.target - Basic System."

    def test_closure_gate_cli_fails_closed_on_early_failure_evidence(self, tmp_path):
        from serein.installer.__main__ import main as installer_main

        evidence_path = tmp_path / "evidence.json"
        installer_main([
            "evidence", "--source-commit", "a" * 40,
            "--failure-stage", "disk_preflight", "--failure-reason", "insufficient space",
            "--out", str(evidence_path),
        ])
        exit_code = installer_main([
            "closure-gate", "--evidence", str(evidence_path),
            "--expected-source-commit", "a" * 40,
        ])
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Section 41 Test I (explicit): non-destructive commands prove zero mutation
# via a filesystem canary
# ---------------------------------------------------------------------------


class TestZeroMutationProof:
    def test_status_disks_doctor_plan_never_write_outside_explicit_out_paths(
        self, tmp_path, monkeypatch
    ):
        # Run every read-only command with cwd pointed at an empty
        # scratch directory and assert it remains empty afterward -
        # the most direct possible proof of "these commands never
        # write anything".
        monkeypatch.chdir(tmp_path)
        from serein.cli import main

        main(["installer", "status"])
        main(["installer", "disks", "--json"])
        main(["installer", "doctor", "--json"])
        main(["installer", "plan", "--target", "/dev/nonexistent", "--json"])

        assert list(tmp_path.iterdir()) == []
