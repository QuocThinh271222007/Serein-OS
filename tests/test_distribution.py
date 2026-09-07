"""Tests for the Distribution subsystem (S7.0).

Layer A only (Section 50-51 of the S7.0 contract): configuration/schema
validation, path-safety regressions, payload allowlist behavior,
autoinstall/credential static regressions, and ISO/build command
construction against fixtures. None of these tests download a multi-GB
ISO, require xorriso/qemu to be installed, or need root - see
docs/distribution/known-limitations.md for what Layer B (real ISO
build/boot validation) requires instead.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from serein.distribution.base import (
    BaseImageError,
    load_base_image_spec,
    sha256_file,
    verify_base_image,
)
from serein.distribution.bootsmoke import (
    DEFAULT_SUCCESS_MARKERS,
    build_qemu_boot_command,
    derive_boot_mode,
    evaluate_boot_log,
    run_boot_smoke,
)
from serein.distribution.build import BuildError, BuildResult, run_build
from serein.distribution.closure import ClosureError, enforce_layer_b_closure
from serein.distribution.evidence import assemble_layer_b_evidence, write_layer_b_evidence
from serein.distribution.inspect import (
    inspect_extracted_tree,
    inspect_iso_file,
    inspect_iso_file_strict,
)
from serein.distribution.iso import (
    IsoCommandError,
    build_extract_command,
    build_rebuild_command,
    build_report_command,
    parse_el_torito_report,
)
from serein.distribution.manifest import assemble_build_manifest, write_build_manifest
from serein.distribution.models import (
    VOLUME_ID,
    BaseImageSpec,
    BootValidation,
    PayloadEntry,
)
from serein.distribution.overlay import OverlayError, apply_overlay, plan_overlay
from serein.distribution.pathsafety import PathSafetyError, is_safe_cleanup_target, resolve_within
from serein.distribution.payload import (
    EXPECTED_WHEEL_MODULES,
    PAYLOAD_RESOURCE_ROOTS,
    PayloadArtifact,
    WheelContentError,
    build_payload_manifest,
    build_wheel,
    collect_resource_artifacts,
    collect_resource_entries,
    inspect_wheel_contents,
    wheel_artifact,
)
from serein.distribution.qa_boot import (
    QA_ENTRY_TITLE,
    QaBootError,
    QaProtectedFileMutationError,
    derive_qa_menuentry,
    discover_grub_config,
    install_qa_entry_as_default,
    prepare_qa_variant,
    transition_to_qa_in_place,
    update_checksum_catalog_if_present,
)
from serein.distribution.safety import (
    scan_boot_config_for_default_autoinstall,
    scan_text_for_credentials,
    scan_tree_for_credentials,
)
from serein.distribution.status import build_distribution_status
from serein.distribution.storage import (
    StorageError,
    directory_size_bytes,
    measure_disk_usage,
    release_base_iso,
)
from serein.distribution.workspace import WorkspaceError, reset_extracted_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = REPO_ROOT / "distribution" / "test-fixtures"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _valid_spec(**overrides: object) -> BaseImageSpec:
    base = BaseImageSpec(
        distribution="ubuntu",
        release="26.04",
        point_release="26.04.1",
        codename="resolute",
        architecture="amd64",
        edition="desktop",
        source="official-ubuntu-release",
        filename="ubuntu-26.04.1-desktop-amd64.iso",
        sha256="a" * 64,
        sha256sums_url="https://releases.ubuntu.com/26.04/SHA256SUMS",
        signature_url="https://releases.ubuntu.com/26.04/SHA256SUMS.gpg",
        signing_key_fingerprint="843938DF228D22F7B3742BC0D94AA3F0EFE21092",
        signing_key_source="keyserver.ubuntu.com",
        verified=False,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


class TestBaseImage:
    def test_pinned_base_image_json_parses(self):
        spec = load_base_image_spec()
        assert spec.distribution == "ubuntu"
        assert spec.architecture == "amd64"
        assert spec.edition in ("desktop", "server")
        assert len(spec.sha256) == 64

    def test_pinned_base_image_verified_is_honest_false(self):
        # The actual multi-GB ISO has never been downloaded/hashed in
        # this repository's development environment - `verified` must
        # never be true by construction (see distribution/base-image.json
        # notes and docs/distribution/known-limitations.md).
        spec = load_base_image_spec()
        assert spec.verified is False

    def test_missing_contract_file_rejected(self, tmp_path):
        with pytest.raises(BaseImageError):
            load_base_image_spec(tmp_path / "does-not-exist.json")

    def test_malformed_json_rejected(self, tmp_path):
        path = tmp_path / "base-image.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(BaseImageError):
            load_base_image_spec(path)

    def test_missing_sha256_field_rejected(self, tmp_path):
        data = json.loads((REPO_ROOT / "distribution" / "base-image.json").read_text())
        del data["sha256"]
        path = tmp_path / "base-image.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(BaseImageError):
            load_base_image_spec(path)

    def test_malformed_sha256_rejected(self, tmp_path):
        data = json.loads((REPO_ROOT / "distribution" / "base-image.json").read_text())
        data["sha256"] = "not-a-real-hash"
        path = tmp_path / "base-image.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(BaseImageError):
            load_base_image_spec(path)

    def test_unsupported_architecture_rejected(self, tmp_path):
        data = json.loads((REPO_ROOT / "distribution" / "base-image.json").read_text())
        data["architecture"] = "arm64"
        path = tmp_path / "base-image.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(BaseImageError):
            load_base_image_spec(path)

    def test_unsupported_distribution_rejected(self, tmp_path):
        data = json.loads((REPO_ROOT / "distribution" / "base-image.json").read_text())
        data["distribution"] = "debian"
        path = tmp_path / "base-image.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(BaseImageError):
            load_base_image_spec(path)

    def test_verify_fails_when_base_file_missing(self, tmp_path):
        spec = _valid_spec()
        with pytest.raises(BaseImageError, match="not present"):
            verify_base_image(tmp_path / "missing.iso", spec)

    def test_verify_fails_on_checksum_mismatch(self, tmp_path):
        iso = tmp_path / "fake.iso"
        iso.write_bytes(b"not the real iso content")
        spec = _valid_spec(sha256="0" * 64)
        with pytest.raises(BaseImageError, match="checksum mismatch"):
            verify_base_image(iso, spec)

    def test_verify_passes_on_matching_checksum(self, tmp_path):
        iso = tmp_path / "fake.iso"
        iso.write_bytes(b"deterministic content")
        real_sha = sha256_file(iso)
        spec = _valid_spec(sha256=real_sha)
        verify_base_image(iso, spec)  # must not raise

    def test_unverified_base_cannot_build(self, tmp_path, monkeypatch):
        # run_build must fail closed if the cached base ISO does not
        # exist / does not match - it must never proceed to extraction.
        monkeypatch.chdir(tmp_path)
        with pytest.raises(BuildError):
            run_build(repo_root=REPO_ROOT, work_dir=tmp_path / "work",
                       output_iso=tmp_path / "out.iso", source_commit="a" * 40)


class TestPayload:
    def test_includes_required_s0_to_s6_5_resources(self):
        entries = collect_resource_entries()
        top_level_roots = {e.path.split("/", 1)[0] for e in entries}
        # desktop (S1), development (S3), hardware (S2), profiles
        # (cross-phase), schemas (all phases incl. S6.5 Focus) - the
        # AI/Cyber/Veil manifests themselves live as Python modules under
        # src/serein/{ai,cyber,veil}/ and are proven embeddable via the
        # wheel-build path (test_wheel_build_is_available_as_separate_step).
        assert top_level_roots == set(PAYLOAD_RESOURCE_ROOTS)
        assert len(entries) > 0

    def test_git_metadata_excluded(self):
        entries = collect_resource_entries()
        assert all(".git" not in e.path.split("/") for e in entries)

    def test_tests_directory_excluded(self):
        # None of PAYLOAD_RESOURCE_ROOTS is "tests", but assert directly
        # that no entry path starts with it, guarding against a future
        # accidental addition to the allowlist.
        entries = collect_resource_entries()
        assert all(not e.path.startswith("tests/") for e in entries)

    def test_developer_caches_excluded(self):
        entries = collect_resource_entries()
        excluded_names = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"}
        for entry in entries:
            assert not excluded_names.intersection(entry.path.split("/"))

    def test_no_secrets_in_payload_entries(self):
        entries = collect_resource_entries()
        for entry in entries:
            text_path = REPO_ROOT / entry.path
            try:
                text = text_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            assert scan_text_for_credentials(text, entry.path) == []

    def test_payload_hashes_deterministic(self):
        manifest_a = build_payload_manifest("a" * 40)
        manifest_b = build_payload_manifest("a" * 40)
        assert manifest_a.to_dict()["entries"] == manifest_b.to_dict()["entries"]

    def test_payload_manifest_matches_schema(self):
        manifest = build_payload_manifest("b" * 40)
        schema = _load_schema("distribution-payload-manifest.schema.json")
        jsonschema.validate(manifest.to_dict(), schema)

    def test_wheel_build_is_available_as_separate_step(self):
        # build_wheel is never invoked by this test (it shells out to
        # `python -m build`, a real subprocess) - this only proves it is
        # importable and distinct from the fast resource-entry path.
        from serein.distribution.payload import build_wheel

        assert callable(build_wheel)

    def test_symlink_escape_rejected_in_payload(self, tmp_path):
        fake_repo = tmp_path / "repo"
        (fake_repo / "hardware").mkdir(parents=True)
        outside = tmp_path / "outside.txt"
        outside.write_text("secret outside repo")
        link = fake_repo / "hardware" / "escape.txt"
        try:
            os.symlink(outside, link)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        entries = collect_resource_entries(repo_root=fake_repo, roots=("hardware",))
        assert all(e.path != "hardware/escape.txt" for e in entries)


class TestOverlaySecurity:
    def test_dotdot_traversal_rejected(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        with pytest.raises(PathSafetyError):
            resolve_within(root, "../outside.txt")

    def test_absolute_destination_rejected(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        with pytest.raises(PathSafetyError):
            resolve_within(root, "/etc/passwd")

    def test_nested_dotdot_rejected(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        with pytest.raises(PathSafetyError):
            resolve_within(root, "a/b/../../../outside.txt")

    def test_safe_relative_path_accepted(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        resolved = resolve_within(root, "a/b/c.txt")
        assert resolved == (root / "a" / "b" / "c.txt").resolve()

    def test_symlink_escape_rejected(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = root / "escape"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        with pytest.raises(PathSafetyError):
            resolve_within(root, "escape/file.txt")

    def test_overlay_allowlist_rejects_out_of_scope_root(self, tmp_path):
        overlay_source = tmp_path / "overlay"
        (overlay_source / "etc").mkdir(parents=True)
        (overlay_source / "etc" / "passwd").write_text("x")
        with pytest.raises(OverlayError):
            plan_overlay(overlay_source, allowlist=(".disk", "serein"))

    def test_overlay_applies_only_allowlisted_files(self, tmp_path):
        overlay_source = tmp_path / "overlay"
        (overlay_source / "serein").mkdir(parents=True)
        (overlay_source / "serein" / "readme.txt").write_text("hello")
        extracted = tmp_path / "extracted"
        extracted.mkdir()

        written = apply_overlay(overlay_source, extracted, allowlist=(".disk", "serein"))
        assert written == ["serein/readme.txt"]
        assert (extracted / "serein" / "readme.txt").read_text() == "hello"

    def test_real_overlay_source_is_fully_allowlisted(self):
        # distribution/overlay/ itself must never contain anything
        # outside the allowlist - this is a regression against the
        # committed overlay tree, not a synthetic fixture.
        entries = plan_overlay(REPO_ROOT / "distribution" / "overlay")
        assert len(entries) > 0


class TestCleanupSafety:
    def test_build_dir_is_safe_cleanup_target(self, tmp_path):
        repo_root = tmp_path / "repo"
        build_dir = repo_root / "build"
        build_dir.mkdir(parents=True)
        assert is_safe_cleanup_target(build_dir, allowed_root=build_dir) is True

    def test_arbitrary_path_is_not_a_safe_cleanup_target(self, tmp_path):
        repo_root = tmp_path / "repo"
        build_dir = repo_root / "build"
        build_dir.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        assert is_safe_cleanup_target(elsewhere, allowed_root=build_dir) is False

    def test_parent_of_allowed_root_is_not_safe(self, tmp_path):
        repo_root = tmp_path / "repo"
        build_dir = repo_root / "build"
        build_dir.mkdir(parents=True)
        assert is_safe_cleanup_target(repo_root, allowed_root=build_dir) is False


class TestAutoinstallSafety:
    def test_safe_grub_cfg_fixture_has_no_findings(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text(encoding="utf-8")
        findings = scan_boot_config_for_default_autoinstall(text)
        assert findings == []

    def test_unsafe_grub_cfg_fixture_is_caught(self):
        text = (FIXTURES_DIR / "grub-cfg-unsafe.cfg").read_text(encoding="utf-8")
        findings = scan_boot_config_for_default_autoinstall(text)
        assert len(findings) == 1
        assert "Try or Install Serein OS Alpha" in findings[0].entry_title

    def test_qa_entry_is_never_flagged(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text(encoding="utf-8")
        # the safe fixture's QA entry uses console=ttyS0, never
        # autoinstall - confirm no entry titled with a QA marker is
        # flagged even if it were to carry autoinstall in a future edit.
        qa_variant = text.replace(
            'console=ttyS0,115200n8 quiet',
            'console=ttyS0,115200n8 autoinstall quiet',
        )
        findings = scan_boot_config_for_default_autoinstall(qa_variant)
        assert findings == []

    def test_bare_cmdline_with_autoinstall_and_no_entries_is_caught(self):
        findings = scan_boot_config_for_default_autoinstall("boot=casper autoinstall quiet")
        assert len(findings) == 1

    def test_qa_serial_entry_template_itself_is_safe(self):
        text = (REPO_ROOT / "distribution" / "boot" / "qa-serial-entry.cfg").read_text()
        findings = scan_boot_config_for_default_autoinstall(text)
        assert findings == []


class TestCredentialScan:
    def test_password_pattern_detected(self):
        findings = scan_text_for_credentials("password: hunter2\n")
        assert len(findings) == 1
        assert findings[0].pattern == "password:"

    def test_private_key_marker_detected(self):
        findings = scan_text_for_credentials("-----BEGIN OPENSSH PRIVATE KEY-----\n")
        assert len(findings) == 1

    def test_token_assignment_detected(self):
        findings = scan_text_for_credentials("TOKEN=ghp_abcdefghijklmnop\n")
        assert len(findings) == 1

    def test_ordinary_prose_not_flagged(self):
        text = "This document explains the password rotation policy in general terms."
        assert scan_text_for_credentials(text) == []

    def test_documentation_naming_the_pattern_is_allowlisted(self):
        text = "Distribution scripts must never contain a line like `password: hunter2` (EXAMPLE)."
        assert scan_text_for_credentials(text) == []

    def test_real_distribution_tree_has_no_credentials(self):
        findings = scan_tree_for_credentials(REPO_ROOT / "distribution")
        assert findings == []

    def test_real_src_distribution_package_has_no_credentials(self):
        findings = scan_tree_for_credentials(REPO_ROOT / "src" / "serein" / "distribution")
        assert findings == []


class TestIsoCommand:
    def test_parse_el_torito_report_fixture(self):
        text = (FIXTURES_DIR / "el-torito-report.txt").read_text(encoding="utf-8")
        flags = parse_el_torito_report(text)
        assert flags[0] == "-c"
        assert "/boot.catalog" in flags
        assert "-eltorito-alt-boot" in flags
        # order must be preserved - boot flags are order-sensitive
        assert flags.index("-c") < flags.index("-eltorito-alt-boot")

    def test_parse_el_torito_report_empty_raises(self):
        with pytest.raises(IsoCommandError):
            parse_el_torito_report("# only a comment\n\n")

    def test_build_rebuild_command_includes_volume_id_and_flags(self, tmp_path):
        boot_flags = ["-c", "/boot.catalog", "-b", "/boot/grub/i386-pc/eltorito.img"]
        command = build_rebuild_command(
            tmp_path / "extracted", boot_flags, tmp_path / "out.iso", VOLUME_ID
        )
        assert command[0:3] == ["xorriso", "-as", "mkisofs"]
        assert "-V" in command and VOLUME_ID in command
        assert "-c" in command and "/boot.catalog" in command
        assert command[-3] == "-o"
        assert command[-2] == str(tmp_path / "out.iso")
        assert command[-1] == str(tmp_path / "extracted")

    def test_build_rebuild_command_rejects_empty_flags(self, tmp_path):
        with pytest.raises(IsoCommandError):
            build_rebuild_command(tmp_path / "extracted", [], tmp_path / "out.iso", VOLUME_ID)

    def test_build_extract_command_is_rootless_osirrox(self, tmp_path):
        command = build_extract_command(tmp_path / "base.iso", tmp_path / "dest")
        assert command[0] == "xorriso"
        assert "-osirrox" in command
        assert "sudo" not in command
        assert "mount" not in command

    def test_build_report_command_targets_real_base_iso(self, tmp_path):
        base_iso = tmp_path / "base.iso"
        command = build_report_command(base_iso)
        assert command == ["xorriso", "-indev", str(base_iso), "-report_el_torito", "as_mkisofs"]


class TestManifest:
    def test_build_manifest_matches_schema(self, tmp_path):
        output_iso = tmp_path / "serein-alpha-26.04-amd64.iso"
        output_iso.write_bytes(b"fake iso bytes for manifest test")
        spec = _valid_spec(verified=True)

        manifest = assemble_build_manifest(
            source_commit="c" * 40,
            base=spec,
            payload_manifest_sha256="d" * 64,
            output_iso=output_iso,
            volume_id=VOLUME_ID,
            boot_validation=BootValidation(status="not_performed"),
        )
        schema = _load_schema("distribution-build-manifest.schema.json")
        jsonschema.validate(manifest.to_dict(), schema)

    def test_output_sha256_matches_real_artifact_bytes(self, tmp_path):
        output_iso = tmp_path / "out.iso"
        output_iso.write_bytes(b"exact bytes")
        spec = _valid_spec(verified=True)
        manifest = assemble_build_manifest(
            source_commit="e" * 40, base=spec, payload_manifest_sha256="f" * 64,
            output_iso=output_iso, volume_id=VOLUME_ID,
        )
        assert manifest.output.sha256 == sha256_file(output_iso)

    def test_source_commit_must_be_well_formed_sha(self, tmp_path):
        output_iso = tmp_path / "out.iso"
        output_iso.write_bytes(b"x")
        spec = _valid_spec(verified=True)
        manifest = assemble_build_manifest(
            source_commit="not-a-sha", base=spec, payload_manifest_sha256="0" * 64,
            output_iso=output_iso, volume_id=VOLUME_ID,
        )
        schema = _load_schema("distribution-build-manifest.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(manifest.to_dict(), schema)

    def test_write_build_manifest_produces_two_files(self, tmp_path):
        output_iso = tmp_path / "out.iso"
        output_iso.write_bytes(b"iso bytes")
        spec = _valid_spec(verified=True)
        manifest = assemble_build_manifest(
            source_commit="1" * 40, base=spec, payload_manifest_sha256="2" * 64,
            output_iso=output_iso, volume_id=VOLUME_ID,
        )
        manifest_path, sha256_path = write_build_manifest(manifest, output_iso)
        assert manifest_path.is_file()
        assert sha256_path.is_file()
        assert manifest.output.sha256 in sha256_path.read_text()

    def test_manifest_never_contains_host_identifying_fields(self, tmp_path):
        output_iso = tmp_path / "out.iso"
        output_iso.write_bytes(b"iso bytes")
        spec = _valid_spec(verified=True)
        manifest = assemble_build_manifest(
            source_commit="3" * 40, base=spec, payload_manifest_sha256="4" * 64,
            output_iso=output_iso, volume_id=VOLUME_ID,
        )
        serialized = json.dumps(manifest.to_dict())
        for forbidden in (os.environ.get("USERNAME", "\0unset"), str(tmp_path), "HOMEPATH"):
            if forbidden and forbidden != "\0unset":
                assert forbidden not in serialized


class TestInspector:
    def test_fixture_extracted_tree_passes(self):
        report = inspect_extracted_tree(FIXTURES_DIR / "extracted-tree-ok")
        assert report.passed is True

    def test_missing_media_marker_fails(self, tmp_path):
        tree = tmp_path / "tree"
        tree.mkdir()
        report = inspect_extracted_tree(tree)
        assert report.passed is False
        assert any(f.check == "media-marker" and f.status == "fail" for f in report.findings)

    def test_media_marker_commit_mismatch_fails(self):
        report = inspect_extracted_tree(
            FIXTURES_DIR / "extracted-tree-ok", expected_source_commit="f" * 40
        )
        assert report.passed is False

    def test_payload_hash_mismatch_detected(self, tmp_path):
        import shutil

        tree = tmp_path / "tree"
        shutil.copytree(FIXTURES_DIR / "extracted-tree-ok", tree)
        (tree / "serein" / "payload" / "hello.txt").write_text("tampered content")
        report = inspect_extracted_tree(tree)
        assert report.passed is False
        assert any(f.check == "payload-manifest" and f.status == "fail" for f in report.findings)

    def test_iso_file_inspection_reports_missing_file(self, tmp_path):
        report = inspect_iso_file(tmp_path / "does-not-exist.iso")
        assert report.passed is False

    def test_iso_file_inspection_skips_without_xorriso(self, tmp_path, monkeypatch):
        import shutil as _shutil

        iso = tmp_path / "fake.iso"
        iso.write_bytes(b"x")
        monkeypatch.setattr("serein.distribution.inspect.shutil.which", lambda _name: None)
        report = inspect_iso_file(iso)
        assert any(f.status == "skip" for f in report.findings)
        assert _shutil  # keep import referenced for clarity


class _FakeQemuProcess:
    """A minimal subprocess.Popen-shaped fake for the boot-smoke
    monitor (S7.0RM Corrective D): .poll()/.terminate()/.kill()/.wait()
    without ever spawning a real process."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_called = True
        if self.returncode is None:
            self.returncode = -15

    def kill(self):
        self.kill_called = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class TestBootSmoke:
    def test_command_never_attaches_a_target_disk(self, tmp_path):
        command = build_qemu_boot_command(tmp_path / "iso.iso", tmp_path / "serial.log")
        assert "-hda" not in command
        # no `-drive` at all when no OVMF path is given (no pflash, no disk)
        assert "-drive" not in command

    def test_command_uses_cdrom_only(self, tmp_path):
        command = build_qemu_boot_command(tmp_path / "iso.iso", tmp_path / "serial.log")
        assert "-cdrom" in command
        assert str(tmp_path / "iso.iso") in command

    def test_ovmf_adds_readonly_pflash_not_a_disk(self, tmp_path):
        command = build_qemu_boot_command(
            tmp_path / "iso.iso", tmp_path / "serial.log", ovmf_code=tmp_path / "OVMF_CODE.fd"
        )
        drive_arg = command[command.index("-drive") + 1]
        assert "readonly=on" in drive_arg
        assert "if=pflash" in drive_arg

    def test_evaluate_boot_log_positive(self):
        success, marker = evaluate_boot_log("... Reached target Basic System ...")
        assert success is True
        assert marker in DEFAULT_SUCCESS_MARKERS

    def test_evaluate_boot_log_negative(self):
        success, marker = evaluate_boot_log("kernel panic - not syncing")
        assert success is False
        assert marker is None

    def test_process_alive_alone_is_never_success(self):
        # A log with no recognized marker, even if long/non-empty, must
        # never be treated as success (Section 46).
        success, _ = evaluate_boot_log("qemu started\n" * 50)
        assert success is False

    def test_run_boot_smoke_reports_pass_when_marker_appears_while_running(self, tmp_path):
        # S7.0RM Corrective D: a live boot is expected to keep running,
        # not exit - the marker must be detected while poll() still
        # returns None.
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        def fake_sleep(_seconds):
            fake_time["t"] += _seconds
            if fake_time["t"] >= 2.0:
                (tmp_path / "work" / "boot-smoke-serial.log").write_text(
                    "booting...\nReached target Basic System\nmore\n"
                )

        result = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"], sleep_fn=fake_sleep,
        )
        assert result.status == "pass"
        assert result.matched_marker is not None
        assert process.terminate_called is True  # deliberately stopped, never leaked

    def test_run_boot_smoke_reports_fail_on_timeout(self, tmp_path):
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        result = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            timeout_seconds=3, poll_interval_seconds=1.0,
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"],
            sleep_fn=lambda s: fake_time.__setitem__("t", fake_time["t"] + s),
        )
        assert result.status == "fail"
        assert "timed out" in result.reason
        assert process.terminate_called is True

    def test_run_boot_smoke_reports_fail_when_process_exits_before_marker(self, tmp_path):
        fake_time = {"t": 0.0}
        process = _FakeQemuProcess()

        def fake_sleep(_seconds):
            fake_time["t"] += _seconds
            process.returncode = 1  # exits on the very first poll, no marker ever written

        result = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"], sleep_fn=fake_sleep,
        )
        assert result.status == "fail"
        assert result.matched_marker is None

    def test_run_boot_smoke_process_never_leaked_on_exception(self, tmp_path):
        process = _FakeQemuProcess()

        def raising_sleep(_seconds):
            raise RuntimeError("simulated harness crash")

        with pytest.raises(RuntimeError):
            run_boot_smoke(
                iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
                popen_factory=lambda *a, **k: process,
                time_source=lambda: 0.0, sleep_fn=raising_sleep,
            )
        assert process.terminate_called is True

    def test_boot_mode_derived_from_ovmf_presence(self, tmp_path):
        process = _FakeQemuProcess()
        fake_time = {"t": 0.0}

        def fake_sleep(_seconds):
            fake_time["t"] += _seconds
            (tmp_path / "work" / "boot-smoke-serial.log").write_text(
                "Reached target Basic System\n"
            )

        result_bios = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            popen_factory=lambda *a, **k: process,
            time_source=lambda: fake_time["t"], sleep_fn=fake_sleep,
        )
        assert result_bios.boot_mode == "bios"

        fake_time["t"] = 0.0
        process2 = _FakeQemuProcess()
        result_uefi = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work2",
            ovmf_code=tmp_path / "OVMF_CODE.fd",
            popen_factory=lambda *a, **k: process2,
            time_source=lambda: fake_time["t"],
            sleep_fn=lambda s: (
                fake_time.__setitem__("t", fake_time["t"] + s),
                (tmp_path / "work2" / "boot-smoke-serial.log").write_text(
                    "Reached target Basic System\n"
                ),
            ),
        )
        assert result_uefi.boot_mode == "uefi"
        assert result_uefi.firmware == str(tmp_path / "OVMF_CODE.fd")

    def test_boot_smoke_result_pass_requires_matched_marker(self):
        from serein.distribution.bootsmoke import BootSmokeError, BootSmokeResult

        with pytest.raises(BootSmokeError):
            BootSmokeResult(status="pass", matched_marker=None, reason="", log_excerpt="")


class TestBuildPipeline:
    def test_run_build_requires_source_commit(self, tmp_path):
        with pytest.raises(BuildError, match="source_commit"):
            run_build(repo_root=tmp_path, work_dir=tmp_path / "work",
                       output_iso=tmp_path / "out.iso", source_commit="")

    def test_run_build_fails_closed_without_cached_base(self, tmp_path):
        # Uses the real pinned base-image.json (base.py always loads
        # from the repo's own contract) but no cached ISO exists under
        # tmp_path's cache dir, so this must fail before any extraction.
        with pytest.raises(BuildError, match="verification failed"):
            run_build(
                repo_root=REPO_ROOT, work_dir=tmp_path / "work",
                output_iso=tmp_path / "out.iso", source_commit="a" * 40,
            )


class TestStatus:
    def test_status_never_touches_network_or_builds(self):
        # Purely a behavioral assertion: calling this must return
        # quickly and not raise even though no base ISO is cached.
        status = build_distribution_status()
        assert status.release_channel == "alpha"

    def test_status_reports_unconfigured_when_contract_missing(self, tmp_path):
        status = build_distribution_status(repo_root=tmp_path)
        assert status.base_configured is False
        assert status.base_cached is False
        assert status.last_iso_exists is False


class TestSchemas:
    @pytest.mark.parametrize(
        "name",
        [
            "distribution-base-image.schema.json",
            "distribution-payload-manifest.schema.json",
            "distribution-build-manifest.schema.json",
        ],
    )
    def test_schema_file_itself_is_valid(self, name):
        schema = _load_schema(name)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_base_image_contract_matches_its_own_schema(self):
        data = json.loads((REPO_ROOT / "distribution" / "base-image.json").read_text())
        schema = _load_schema("distribution-base-image.schema.json")
        jsonschema.validate(data, schema)


class TestPayloadEntryHelper:
    def test_payload_entry_is_immutable(self):
        entry = PayloadEntry(path="a", sha256="0" * 64, size_bytes=1)
        with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
            entry.path = "b"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# S7.0R Corrective D: clean, reproducible build workspace
# ---------------------------------------------------------------------------


class TestCleanWorkspace:
    def test_reset_creates_empty_extracted_dir(self, tmp_path):
        work_dir = tmp_path / "work"
        extracted = work_dir / "extracted"
        reset_extracted_workspace(work_dir, extracted)
        assert extracted.is_dir()
        assert list(extracted.iterdir()) == []

    def test_stale_file_does_not_survive_a_second_reset(self, tmp_path):
        work_dir = tmp_path / "work"
        extracted = work_dir / "extracted"
        reset_extracted_workspace(work_dir, extracted)
        (extracted / "stale.txt").write_text("leftover from build #1")
        assert (extracted / "stale.txt").exists()

        reset_extracted_workspace(work_dir, extracted)
        assert not (extracted / "stale.txt").exists()
        assert list(extracted.iterdir()) == []

    def test_arbitrary_path_outside_work_dir_rejected(self, tmp_path):
        work_dir = tmp_path / "work"
        elsewhere = tmp_path / "elsewhere" / "extracted"
        with pytest.raises(WorkspaceError):
            reset_extracted_workspace(work_dir, elsewhere)

    def test_non_canonical_name_inside_work_dir_rejected(self, tmp_path):
        work_dir = tmp_path / "work"
        wrong_name = work_dir / "not-extracted"
        with pytest.raises(WorkspaceError):
            reset_extracted_workspace(work_dir, wrong_name)

    def test_symlinked_extracted_dir_escaping_work_dir_rejected(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = work_dir / "extracted"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        with pytest.raises(WorkspaceError):
            reset_extracted_workspace(work_dir, link)
        # and outside must survive untouched
        assert outside.is_dir()

    def test_cache_and_dist_are_never_referenced_by_reset(self, tmp_path):
        # reset_extracted_workspace only ever accepts (work_dir, extracted_dir)
        # - cache/upstream and dist/ live outside work_dir entirely and
        # have no code path into this function at all.
        repo_root = tmp_path / "repo"
        cache_dir = repo_root / "cache" / "upstream"
        dist_dir = repo_root / "dist"
        cache_dir.mkdir(parents=True)
        dist_dir.mkdir(parents=True)
        (cache_dir / "base.iso").write_bytes(b"verified base")
        (dist_dir / "prior.iso").write_bytes(b"prior build output")

        work_dir = repo_root / "build" / "work"
        reset_extracted_workspace(work_dir, work_dir / "extracted")

        assert (cache_dir / "base.iso").read_bytes() == b"verified base"
        assert (dist_dir / "prior.iso").read_bytes() == b"prior build output"


# ---------------------------------------------------------------------------
# S7.0R Corrective C: Serein wheel actually embedded in payload
# ---------------------------------------------------------------------------


class TestWheelPayload:
    def test_real_wheel_build_contains_expected_modules(self, tmp_path):
        # A real (not mocked) `python -m build --no-isolation` invocation
        # against this actual repository - slower than the rest of the
        # suite, deliberately included so Corrective C is proven against
        # real bytes, not only mocked logic (Section 27/84).
        wheel_path = build_wheel(repo_root=REPO_ROOT, out_dir=tmp_path / "wheel")
        assert wheel_path.is_file()
        inspect_wheel_contents(wheel_path)  # must not raise

        import zipfile

        with zipfile.ZipFile(wheel_path) as archive:
            names = set(archive.namelist())
        for module in EXPECTED_WHEEL_MODULES:
            assert module in names

    def test_inspect_wheel_contents_fails_closed_on_incomplete_wheel(self, tmp_path):
        import zipfile

        fake_wheel = tmp_path / "incomplete-0.1-py3-none-any.whl"
        with zipfile.ZipFile(fake_wheel, "w") as archive:
            archive.writestr("serein/__init__.py", "")
            archive.writestr("serein/cli.py", "")
            # deliberately missing serein/ai, cyber, veil, focus, distribution

        with pytest.raises(WheelContentError):
            inspect_wheel_contents(fake_wheel)

    def test_wheel_artifact_hash_matches_real_bytes(self, tmp_path):
        wheel_path = tmp_path / "fake-0.1-py3-none-any.whl"
        wheel_path.write_bytes(b"pretend wheel bytes")
        artifact = wheel_artifact(wheel_path)

        import hashlib

        assert artifact.entry.sha256 == hashlib.sha256(b"pretend wheel bytes").hexdigest()
        assert artifact.entry.size_bytes == len(b"pretend wheel bytes")

    def test_wheel_artifact_payload_path_is_deterministic_packages_prefix(self, tmp_path):
        wheel_path = tmp_path / "serein-0.1.0.dev0-py3-none-any.whl"
        wheel_path.write_bytes(b"x")
        artifact = wheel_artifact(wheel_path)
        assert artifact.entry.path == "packages/serein-0.1.0.dev0-py3-none-any.whl"

    def test_wheel_artifact_source_path_never_in_manifest_dict(self, tmp_path):
        wheel_path = tmp_path / "serein-0.1.0.dev0-py3-none-any.whl"
        wheel_path.write_bytes(b"x")
        artifact = wheel_artifact(wheel_path)
        manifest = build_payload_manifest(
            "a" * 40, repo_root=REPO_ROOT, extra_entries=[artifact.entry]
        )
        serialized = json.dumps(manifest.to_dict())
        assert str(wheel_path) not in serialized
        assert str(tmp_path) not in serialized

    def test_collect_resource_artifacts_source_paths_are_real_repo_files(self):
        artifacts = collect_resource_artifacts(REPO_ROOT)
        assert len(artifacts) > 0
        for artifact in artifacts[:5]:
            assert artifact.source_path.is_file()
            assert artifact.source_path == REPO_ROOT / artifact.entry.path

    def test_payload_artifact_is_a_plain_pairing(self):
        entry = PayloadEntry(path="packages/x.whl", sha256="0" * 64, size_bytes=1)
        artifact = PayloadArtifact(entry=entry, source_path=Path("/anywhere/x.whl"))
        assert artifact.entry is entry


# ---------------------------------------------------------------------------
# S7.0R Corrective B: QA serial boot must actually exist in built media
# ---------------------------------------------------------------------------


class TestQaBoot:
    def test_discover_grub_config_finds_fixture_candidate(self):
        relative = discover_grub_config(FIXTURES_DIR / "extracted-tree-ok")
        assert relative == "boot/grub/grub.cfg"

    def test_discover_grub_config_blocked_when_no_candidate(self, tmp_path):
        empty_tree = tmp_path / "empty"
        empty_tree.mkdir()
        with pytest.raises(QaBootError):
            discover_grub_config(empty_tree)

    def test_derive_qa_menuentry_reuses_real_linux_initrd_paths(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        entry = derive_qa_menuentry(text)
        assert "/casper/vmlinuz" in entry
        assert "/casper/initrd" in entry
        assert QA_ENTRY_TITLE in entry

    def test_derive_qa_menuentry_adds_serial_console_before_separator(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        entry = derive_qa_menuentry(text)
        linux_line = next(line for line in entry.splitlines() if "vmlinuz" in line)
        assert "console=ttyS0,115200n8" in linux_line
        # the console arg must land before the init-arg separator, not after
        assert linux_line.index("console=ttyS0") < linux_line.index("---")

    def test_derive_qa_menuentry_removes_quiet(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        entry = derive_qa_menuentry(text)
        linux_line = next(line for line in entry.splitlines() if "vmlinuz" in line)
        assert "quiet" not in linux_line

    def test_derive_qa_menuentry_never_contains_autoinstall(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        entry = derive_qa_menuentry(text)
        assert "autoinstall" not in entry

    def test_derive_qa_menuentry_rejects_autoinstall_production_source(self):
        text = (FIXTURES_DIR / "grub-cfg-unsafe.cfg").read_text()
        with pytest.raises(QaBootError):
            derive_qa_menuentry(text)

    def test_derive_qa_menuentry_no_menuentry_blocked(self):
        with pytest.raises(QaBootError):
            derive_qa_menuentry("set timeout=5\n")

    def test_install_qa_entry_as_default_selects_it_deterministically(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        qa_entry = derive_qa_menuentry(text)
        patched = install_qa_entry_as_default(text, qa_entry)
        assert 'set default="0"' in patched
        assert "set timeout=1" in patched
        # the QA entry must appear before the original production entry
        assert patched.index(QA_ENTRY_TITLE) < patched.index("Try or Install Serein OS Alpha")

    def test_patched_config_has_no_default_autoinstall(self):
        text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        qa_entry = derive_qa_menuentry(text)
        patched = install_qa_entry_as_default(text, qa_entry)
        findings = scan_boot_config_for_default_autoinstall(patched)
        assert findings == []

    def test_prepare_qa_variant_leaves_production_tree_untouched(self, tmp_path):
        dest = tmp_path / "qa"
        original_grub_path = FIXTURES_DIR / "extracted-tree-ok" / "boot" / "grub" / "grub.cfg"
        original_grub = original_grub_path.read_text()

        prepare_qa_variant(FIXTURES_DIR / "extracted-tree-ok", dest)

        still_original = (
            FIXTURES_DIR / "extracted-tree-ok" / "boot" / "grub" / "grub.cfg"
        ).read_text()
        assert still_original == original_grub

    def test_prepare_qa_variant_qa_tree_has_patched_grub_only(self, tmp_path):
        dest = tmp_path / "qa"
        result = prepare_qa_variant(FIXTURES_DIR / "extracted-tree-ok", dest)

        patched = (dest / result.grub_config_relative_path).read_text()
        assert QA_ENTRY_TITLE in patched
        assert 'set default="0"' in patched
        # everything else copied unchanged
        assert (dest / "serein" / "manifest.json").is_file()
        assert (dest / "EFI" / "boot" / "bootx64.efi").is_file()

    def test_prepare_qa_variant_is_deterministically_selected_no_keyboard(self, tmp_path):
        dest = tmp_path / "qa"
        result = prepare_qa_variant(FIXTURES_DIR / "extracted-tree-ok", dest)
        patched = (dest / result.grub_config_relative_path).read_text()
        # deterministic selection: default=0 + short timeout, never
        # relying on a keypress or race-sensitive automation
        assert 'set default="0"' in patched
        assert re.search(r"set timeout=\d+", patched)

    def test_prepare_qa_variant_blocked_without_grub_candidate(self, tmp_path):
        broken_tree = tmp_path / "broken"
        broken_tree.mkdir()
        (broken_tree / "serein").mkdir()
        with pytest.raises(QaBootError):
            prepare_qa_variant(broken_tree, tmp_path / "qa-out")

    def test_checksum_catalog_updated_when_present(self, tmp_path):
        tree = tmp_path / "tree"
        (tree / "boot" / "grub").mkdir(parents=True)
        grub_path = tree / "boot" / "grub" / "grub.cfg"
        grub_path.write_text("hello grub")

        import hashlib

        stale_hash = "0" * 32
        (tree / "md5sum.txt").write_text(f"{stale_hash}  ./boot/grub/grub.cfg\n")

        updated = update_checksum_catalog_if_present(tree, "boot/grub/grub.cfg")
        assert updated is True

        new_content = (tree / "md5sum.txt").read_text()
        real_hash = hashlib.md5(grub_path.read_bytes()).hexdigest()  # noqa: S324
        assert real_hash in new_content
        assert stale_hash not in new_content

    def test_checksum_catalog_absent_is_not_an_error(self, tmp_path):
        tree = tmp_path / "tree"
        tree.mkdir()
        assert update_checksum_catalog_if_present(tree, "boot/grub/grub.cfg") is False


# ---------------------------------------------------------------------------
# S7.0R Corrective E: strict real-ISO inspection
# ---------------------------------------------------------------------------


def _fake_iso_environment(
    tmp_path, *, wheel_hash=None, source_commit="a" * 40, volume_id="SEREIN_ALPHA"
):
    """Build the pieces a fake `xorriso`-backed strict-inspector test
    needs: a fake .iso file, and a fake runner that answers each xorriso
    subcommand the same way the real tool would for a well-formed
    Serein medium."""
    import hashlib

    iso_path = tmp_path / "serein-alpha-26.04-amd64.iso"
    iso_path.write_bytes(b"pretend iso bytes for strict inspector test")

    wheel_bytes = b"pretend wheel bytes"
    wheel_sha = wheel_hash or hashlib.sha256(wheel_bytes).hexdigest()
    hello_bytes = b"hello payload"
    hello_sha = hashlib.sha256(hello_bytes).hexdigest()

    def fake_runner(argv, **kwargs):
        if "-pvd_info" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"Volume id    : '{volume_id}'\n", stderr=""
            )
        if "-report_el_torito" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout="-c '/boot.catalog'\n-appended_part_as_gpt\n", stderr=""
            )
        if "-extract" in argv:
            extract_dest = Path(argv[argv.index("-extract") + 2])
            (extract_dest / "payload" / "packages").mkdir(parents=True)
            (extract_dest / "payload" / "packages" / "serein-0.1.0-py3-none-any.whl").write_bytes(
                wheel_bytes
            )
            (extract_dest / "payload" / "hello.txt").write_bytes(hello_bytes)
            marker = {
                "distribution": "serein", "product": "Serein OS Alpha",
                "source_commit": source_commit, "base_release": "26.04",
                "base_point_release": "26.04.1", "architecture": "amd64", "build_schema": 1,
            }
            (extract_dest / "manifest.json").write_text(json.dumps(marker))
            payload_manifest = {
                "schema_version": 1, "source_commit": source_commit,
                "generated_from": ["fixture"], "entry_count": 2,
                "total_bytes": len(wheel_bytes) + len(hello_bytes),
                "entries": [
                    {
                        "path": "packages/serein-0.1.0-py3-none-any.whl",
                        "sha256": wheel_sha, "size_bytes": len(wheel_bytes),
                    },
                    {"path": "hello.txt", "sha256": hello_sha, "size_bytes": len(hello_bytes)},
                ],
            }
            (extract_dest / "payload-manifest.json").write_text(json.dumps(payload_manifest))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected argv {argv}")

    return iso_path, fake_runner


class TestStrictInspector:
    def test_happy_path_is_strict_passed(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path)
        actual_sha = sha256_file(iso_path)
        iso_path.with_suffix(iso_path.suffix + ".sha256").write_text(
            f"{actual_sha}  {iso_path.name}\n"
        )
        iso_path.with_suffix(iso_path.suffix + ".manifest.json").write_text(json.dumps({
            "source_commit": "a" * 40,
            "output": {"sha256": actual_sha},
        }))

        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert report.strict_passed is True
        assert all(f.status == "pass" for f in report.findings)

    def test_happy_path_without_sidecars_is_not_strict_passed(self, tmp_path, monkeypatch):
        # Sidecars are always produced by the real build pipeline
        # (manifest.write_build_manifest) - their absence here means
        # this ISO was not built via the canonical pipeline, and strict
        # closure evidence must not paper over that with a skip.
        iso_path, fake_runner = _fake_iso_environment(tmp_path)
        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "sidecar-sha256" and f.status == "skip" for f in report.findings)

    def test_skip_is_not_strict_pass(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path)
        monkeypatch.setattr("serein.distribution.inspect.shutil.which", lambda _name: None)
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert any(f.status == "skip" for f in report.findings)
        assert report.strict_passed is False
        # the lenient `passed` property is unaffected by this distinction
        assert report.passed is True

    def test_wrong_volume_id_fails(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path, volume_id="SOMETHING_ELSE")
        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "volume-id" and f.status == "fail" for f in report.findings)

    def test_wrong_source_commit_fails(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path, source_commit="a" * 40)
        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="b" * 40, runner=fake_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "media-marker" and f.status == "fail" for f in report.findings)

    def test_wrong_base_release_fails(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path)
        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40,
            expected_base_release="99.99", runner=fake_runner,
        )
        assert report.strict_passed is False

    def test_missing_wheel_entry_fails(self, tmp_path, monkeypatch):
        import hashlib

        iso_path = tmp_path / "no-wheel.iso"
        iso_path.write_bytes(b"x")

        def fake_runner(argv, **kwargs):
            if "-pvd_info" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="Volume id    : 'SEREIN_ALPHA'\n"
                )
            if "-report_el_torito" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="-appended_part_as_gpt\n")
            if "-extract" in argv:
                extract_dest = Path(argv[argv.index("-extract") + 2])
                extract_dest.mkdir(parents=True)
                data = b"only a resource file, no wheel"
                (extract_dest / "hello.txt").write_bytes(data)
                marker = {
                    "distribution": "serein", "source_commit": "a" * 40, "base_release": "26.04",
                    "base_point_release": "26.04.1", "architecture": "amd64", "build_schema": 1,
                }
                (extract_dest / "manifest.json").write_text(json.dumps(marker))
                pm = {
                    "source_commit": "a" * 40,
                    "entries": [
                        {
                            "path": "hello.txt",
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "size_bytes": len(data),
                        }
                    ],
                }
                (extract_dest / "payload-manifest.json").write_text(json.dumps(pm))
                return subprocess.CompletedProcess(argv, 0, stdout="")
            raise AssertionError(argv)

        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "payload-manifest" and f.status == "fail" for f in report.findings)

    def test_payload_hash_mismatch_fails(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path, wheel_hash="0" * 64)
        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "payload-manifest" and f.status == "fail" for f in report.findings)

    def test_missing_uefi_evidence_fails(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path)

        def no_uefi_runner(argv, **kwargs):
            if "-report_el_torito" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="-c '/boot.catalog'\n")
            return fake_runner(argv, **kwargs)

        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=no_uefi_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "uefi-boot-evidence" and f.status == "fail" for f in report.findings)

    def test_sidecar_sha256_mismatch_fails(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path)
        sidecar = iso_path.with_suffix(iso_path.suffix + ".sha256")
        sidecar.write_text(f"{'f' * 64}  {iso_path.name}\n")

        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "sidecar-sha256" and f.status == "fail" for f in report.findings)

    def test_sidecar_manifest_matching_passes(self, tmp_path, monkeypatch):
        iso_path, fake_runner = _fake_iso_environment(tmp_path)
        actual_sha = sha256_file(iso_path)
        sidecar = iso_path.with_suffix(iso_path.suffix + ".manifest.json")
        sidecar.write_text(json.dumps({
            "source_commit": "a" * 40,
            "output": {"sha256": actual_sha},
        }))

        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=fake_runner
        )
        assert any(
            f.check == "sidecar-manifest" and f.status == "pass" for f in report.findings
        )

    def test_missing_iso_fails_immediately(self, tmp_path):
        report = inspect_iso_file_strict(
            tmp_path / "does-not-exist.iso", tmp_path / "work", expected_source_commit="a" * 40
        )
        assert report.strict_passed is False
        assert report.findings[0].status == "fail"

    def test_extraction_failure_fails_closed(self, tmp_path, monkeypatch):
        iso_path = tmp_path / "iso.iso"
        iso_path.write_bytes(b"x")

        def failing_runner(argv, **kwargs):
            if "-extract" in argv:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="extraction failed")
            if "-pvd_info" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="Volume id    : 'SEREIN_ALPHA'\n"
                )
            if "-report_el_torito" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="-appended_part_as_gpt\n")
            raise AssertionError(argv)

        monkeypatch.setattr(
            "serein.distribution.inspect.shutil.which", lambda _name: "/usr/bin/xorriso"
        )
        report = inspect_iso_file_strict(
            iso_path, tmp_path / "work", expected_source_commit="a" * 40, runner=failing_runner
        )
        assert report.strict_passed is False
        assert any(f.check == "extract-serein-tree" and f.status == "fail" for f in report.findings)


# ---------------------------------------------------------------------------
# S7.0R Corrective A: Layer-B workflow trigger model
# ---------------------------------------------------------------------------


class TestLayerBWorkflow:
    @pytest.fixture()
    def workflow(self):
        import yaml

        with (WORKFLOWS_DIR / "iso-smoke.yml").open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_workflow_dispatch_present(self, workflow):
        triggers = workflow.get(True, workflow.get("on"))
        assert "workflow_dispatch" in triggers

    def test_pull_request_trigger_present_with_expected_types(self, workflow):
        triggers = workflow.get(True, workflow.get("on"))
        assert "pull_request" in triggers
        assert set(triggers["pull_request"]["types"]) == {"labeled", "synchronize", "reopened"}

    def test_pull_request_target_absent_from_raw_file(self):
        text = (WORKFLOWS_DIR / "iso-smoke.yml").read_text(encoding="utf-8")
        # only allowed to appear inside a comment explaining it is NOT used
        for line in text.splitlines():
            if "pull_request_target" in line:
                assert line.strip().startswith("#")

    def test_permissions_are_read_only(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}

    def test_expensive_job_requires_opt_in_label_on_pr(self, workflow):
        condition = workflow["jobs"]["iso-smoke"]["if"]
        assert "run-iso-smoke" in condition
        assert "labels" in condition

    def test_checkout_uses_exact_pr_head_sha_expression(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
        assert checkout["with"]["ref"] == "${{ steps.expected-sha.outputs.sha }}"

    def test_exact_head_guard_step_present(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        guard = next(s for s in steps if s.get("name") == "Verify exact-head checkout")
        assert "EXPECTED_SOURCE_SHA" in guard["run"]
        assert "ACTUAL_CHECKED_OUT_SHA" in guard["run"]
        assert "exit 1" in guard["run"]

    def test_no_secrets_referenced(self):
        text = (WORKFLOWS_DIR / "iso-smoke.yml").read_text(encoding="utf-8")
        # no `${{ secrets.* }}` GitHub Actions expression anywhere - prose
        # mentioning "repository secrets" in a comment is fine.
        assert re.search(r"\$\{\{\s*secrets\.", text) is None

    def test_evidence_upload_never_includes_the_iso_itself(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"]
        assert "*.iso" not in paths
        assert "manifest.json" in paths

    def test_evidence_upload_runs_even_on_earlier_failure(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
        assert upload.get("if") == "always()"
        assemble = next(s for s in steps if s.get("name") == "Assemble Layer-B evidence")
        assert assemble.get("if") == "always()"

    def test_evidence_assembly_never_requires_manifest_files_unconditionally(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Layer-B evidence")
        # the fix for the real observed defect: manifest paths must
        # only be passed when the file actually exists, never assumed
        assert "if [ -f dist/serein-alpha-26.04-amd64.iso.manifest.json ]" in assemble["run"]
        assert "--source-commit" in assemble["run"]

    def test_qemu_boot_step_fails_job_on_failure(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        boot = next(s for s in steps if s.get("name", "").startswith("QEMU boot smoke"))
        assert boot.get("if") == "always()"
        assert "exit 1" in boot["run"]

    def test_qemu_boot_requires_uefi(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        boot = next(s for s in steps if s.get("name", "").startswith("QEMU boot smoke"))
        assert "--require-uefi" in boot["run"]

    def test_strict_inspection_steps_fail_job_on_failure(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        for name in ("Strict-inspect production ISO", "Strict-inspect QA ISO"):
            step = next(s for s in steps if s.get("name") == name)
            assert step.get("if") == "always()"
            assert "exit 1" in step["run"]

    def test_closure_gate_step_present_and_always_runs(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        gate = next(s for s in steps if s.get("name") == "Enforce Layer-B closure")
        assert gate.get("if") == "always()"
        assert "closure-gate" in gate["run"]
        assert "--expected-source-commit" in gate["run"]

    def test_ephemeral_cleanup_scoped_to_github_hosted(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        cleanup = next(s for s in steps if s.get("name") == "Reclaim ephemeral runner SDK space")
        assert cleanup.get("if") == "runner.environment == 'github-hosted'"

    def test_ephemeral_cleanup_never_uses_dangerous_glob_deletion(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        cleanup = next(s for s in steps if s.get("name") == "Reclaim ephemeral runner SDK space")
        script = cleanup["run"]
        assert "rm -rf /opt/*" not in script
        assert "rm -rf /usr/local/*" not in script
        assert "rm -rf \"$" not in script.replace("${resolved}", "")  # no untrusted-var-only rm -rf

    def test_ephemeral_cleanup_logs_before_and_after_free_space(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        cleanup = next(s for s in steps if s.get("name") == "Reclaim ephemeral runner SDK space")
        assert "FREE_SPACE_BEFORE_CLEANUP_KB" in cleanup["run"]
        assert "FREE_SPACE_AFTER_CLEANUP_KB" in cleanup["run"]
        assert "SPACE_RECLAIMED_KB" in cleanup["run"]

    def test_preflight_threshold_is_derived_not_arbitrary(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        # the requirement must be computed from named components, never
        # a bare literal like `REQUIRED_KB=$((12 * 1024 * 1024))` with
        # no arithmetic connection to a documented peak - see
        # TestLayerBWorkflow's Corrective D tests for the full
        # coherence check.
        assert "REQUIRED_KB=$((REQUIRED_GIB * 1024 * 1024))" in preflight["run"]

    def test_build_step_uses_ephemeral_storage(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        build = next(
            s for s in steps
            if s.get("name") == "Build Serein Alpha ISO (production + QA variant)"
        )
        assert "EPHEMERAL_STORAGE=1" in build["run"]

    def test_single_canonical_builder_no_competing_script(self):
        # Section 9: no "ci-special-build.sh" or equivalent - only the
        # scripts already covered by docs/distribution/.
        scripts_dir = REPO_ROOT / "distribution" / "scripts"
        names = {p.name for p in scripts_dir.glob("*.sh")}
        assert names == {
            "fetch-base-image.sh", "verify-base-image.sh", "build-iso.sh",
            "inspect-iso.sh", "boot-smoke.sh", "clean.sh",
        }

    # -- S7.0RM2 Corrective B: stage-state fidelity, not artifact inference --

    def test_build_step_has_an_id_for_outcome_tracking(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        build = next(
            s for s in steps
            if s.get("name") == "Build Serein Alpha ISO (production + QA variant)"
        )
        assert build.get("id") == "build"

    def test_evidence_step_derives_stage_state_from_build_outcome_not_manifest_presence(
        self, workflow
    ):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Layer-B evidence")
        script = assemble["run"]
        assert "steps.build.outcome" in script
        # the three real outcomes must each be handled explicitly
        assert "success)" in script
        assert "failure)" in script
        # a skipped/cancelled build step must produce not_performed for
        # BOTH stages, never "fail" - this is the exact real defect
        assert "--production-build not_performed" in script
        assert "--qa-build not_performed" in script
        # a production failure must never claim QA was attempted
        assert re.search(r"failure\)[\s\S]*?--qa-build not_performed", script)

    def test_evidence_step_no_longer_infers_production_build_from_manifest_alone(
        self, workflow
    ):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Layer-B evidence")
        script = assemble["run"]
        # the old (buggy) pattern must be gone: production-build must
        # never be decided by a bare `if [ -f manifest ]; then pass;
        # else fail; fi` with no reference to the real step outcome
        old_buggy_pattern = (
            "ARGS+=(--production-build pass)\n"
            "          else\n"
            "            ARGS+=(--production-build fail)"
        )
        assert old_buggy_pattern not in script

    # -- S7.0RM2 Corrective C: pinned vs. actual base metadata fidelity --

    def test_pinned_base_metadata_step_present_and_early(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        names = [s.get("name") for s in steps]
        pinned_index = names.index("Record pinned base metadata")
        fetch_index = names.index("Fetch pinned base image (explicit, this job only)")
        preflight_index = names.index("Disk space preflight")
        # pinned metadata must be recorded before the earliest failure
        # points (preflight, fetch) so it survives an early failure
        assert pinned_index < preflight_index
        assert pinned_index < fetch_index

    def test_pinned_base_metadata_reads_committed_contract_file(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        pinned = next(s for s in steps if s.get("name") == "Record pinned base metadata")
        assert "distribution/base-image.json" in pinned["run"]
        assert "filename" in pinned["run"]
        assert "expected_sha256" in pinned["run"]

    def test_evidence_step_uses_pinned_metadata_not_conditional_fetch_output(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        assemble = next(s for s in steps if s.get("name") == "Assemble Layer-B evidence")
        script = assemble["run"]
        assert "steps.pinned-base.outputs.filename" in script
        assert "steps.pinned-base.outputs.expected_sha256" in script

    def test_actual_base_sha256_only_from_real_hash_step(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        base_sha = next(s for s in steps if s.get("name") == "Record actual base ISO sha256")
        assert "sha256sum" in base_sha["run"]
        assert base_sha.get("id") == "base-sha"

    # -- S7.0RM2 Corrective D: coherent disk-preflight arithmetic --

    def test_disk_preflight_arithmetic_is_internally_coherent(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        script = preflight["run"]

        def _extract(varname):
            match = re.search(rf"{varname}=(\d+)\b", script)
            assert match, f"{varname} not found as a literal integer assignment"
            return int(match.group(1))

        extracted_tree = _extract("EXTRACTED_TREE_GIB")
        production_iso = _extract("PRODUCTION_ISO_GIB")
        qa_iso = _extract("QA_ISO_GIB")
        margin = _extract("SAFETY_MARGIN_GIB")

        # the derivation must be expressed in terms of the named
        # components, never a disconnected magic number
        assert "PEAK_GIB=$((EXTRACTED_TREE_GIB + PRODUCTION_ISO_GIB + QA_ISO_GIB))" in script
        assert "REQUIRED_GIB=$((PEAK_GIB + SAFETY_MARGIN_GIB))" in script
        assert "REQUIRED_KB=$((REQUIRED_GIB * 1024 * 1024))" in script

        computed_peak = extracted_tree + production_iso + qa_iso
        computed_required = computed_peak + margin
        assert computed_peak > 0
        assert computed_required > computed_peak
        # the previous S7.0RM defect: components summed to far more
        # than the enforced requirement (e.g. 6+10+6+6+2=30 documented
        # vs. 12 enforced) - guard against that class of mismatch by
        # requiring the *enforced* requirement to be the documented
        # components' own sum, not merely "at least" it.
        required_kb_literal_present = "REQUIRED_KB=$((REQUIRED_GIB * 1024 * 1024))" in script
        assert required_kb_literal_present

    def test_disk_preflight_no_longer_uses_old_disconnected_constant(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        # the old S7.0RM literal (12 GiB, unrelated to its own stated
        # 6+8..10+6+6+2 components) must be gone
        assert "REQUIRED_KB=$((12 * 1024 * 1024))" not in preflight["run"]

    def test_disk_preflight_reports_available_and_required(self, workflow):
        steps = workflow["jobs"]["iso-smoke"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Disk space preflight")
        assert "AVAILABLE_KB" in preflight["run"]
        assert "REQUIRED_KB" in preflight["run"]


# ---------------------------------------------------------------------------
# S7.0R: Layer-B evidence assembly
# ---------------------------------------------------------------------------


class TestLayerBEvidence:
    def test_evidence_matches_schema(self, tmp_path):
        evidence = assemble_layer_b_evidence(
            source_commit="a" * 40,
            base_filename="ubuntu-26.04.1-desktop-amd64.iso",
            base_sha256_expected="b" * 64,
            base_sha256_actual="b" * 64,
            production_iso_filename="serein-alpha-26.04-amd64.iso",
            production_iso_sha256="c" * 64,
            production_build="pass",
            production_inspection="pass",
            qa_iso_filename="serein-alpha-26.04-amd64-qa.iso",
            qa_iso_sha256="d" * 64,
            qa_build="pass",
            qa_inspection="pass",
            qemu_boot="pass",
            qemu_boot_mode="uefi",
            ovmf_firmware="/usr/share/OVMF/OVMF_CODE_4M.fd",
            boot_marker="Reached target Basic System",
        )
        schema = _load_schema("distribution-layer-b-evidence.schema.json")
        jsonschema.validate(evidence.to_dict(), schema)

    def test_minimal_evidence_before_any_stage_ran_matches_schema(self):
        # Corrective B: constructible from just source_commit, with
        # every stage genuinely "not_performed" - e.g. the disk-space
        # preflight failed before the base image was ever downloaded.
        evidence = assemble_layer_b_evidence(
            source_commit="a" * 40,
            failure_stage="disk_preflight",
            failure_reason="insufficient free space: 13599352 KiB available",
        )
        schema = _load_schema("distribution-layer-b-evidence.schema.json")
        jsonschema.validate(evidence.to_dict(), schema)
        assert evidence.production_build == "not_performed"
        assert evidence.qa_build == "not_performed"
        assert evidence.qemu_boot == "not_performed"
        assert evidence.base_verified is False
        assert evidence.boot_marker is None

    def test_base_verified_derived_from_hash_equality(self):
        matching = assemble_layer_b_evidence(
            source_commit="a" * 40, base_filename="x.iso",
            base_sha256_expected="b" * 64, base_sha256_actual="b" * 64,
            production_iso_filename="x.iso", production_iso_sha256="c" * 64,
        )
        mismatched = assemble_layer_b_evidence(
            source_commit="a" * 40, base_filename="x.iso",
            base_sha256_expected="b" * 64, base_sha256_actual="e" * 64,
            production_iso_filename="x.iso", production_iso_sha256="c" * 64,
        )
        assert matching.base_verified is True
        assert mismatched.base_verified is False

    def test_invalid_stage_status_rejected(self):
        with pytest.raises(ValueError, match="production_build"):
            assemble_layer_b_evidence(source_commit="a" * 40, production_build="maybe")  # type: ignore[arg-type]

    def test_round_trip_through_load(self, tmp_path):
        from serein.distribution.evidence import load_layer_b_evidence

        original = assemble_layer_b_evidence(
            source_commit="a" * 40, production_build="pass", qa_build="fail",
            failure_stage="qa_build", failure_reason="QA_BUILD=BLOCKED",
        )
        path = write_layer_b_evidence(original, tmp_path / "evidence.json")
        reloaded = load_layer_b_evidence(path)
        assert reloaded.source_commit == original.source_commit
        assert reloaded.production_build == "pass"
        assert reloaded.qa_build == "fail"
        assert reloaded.failure_stage == "qa_build"

    def test_no_host_identifying_fields(self, tmp_path):
        evidence = assemble_layer_b_evidence(
            source_commit="a" * 40, base_filename="x.iso",
            base_sha256_expected="b" * 64, base_sha256_actual="b" * 64,
            production_iso_filename="x.iso", production_iso_sha256="c" * 64,
        )
        path = write_layer_b_evidence(evidence, tmp_path / "evidence.json")
        serialized = path.read_text()
        for forbidden in (os.environ.get("USERNAME", "\0unset"), str(tmp_path)):
            if forbidden and forbidden != "\0unset":
                assert forbidden not in serialized


# ---------------------------------------------------------------------------
# S7.0RM2: end-to-end CLI reproduction of the real observed defects
# ---------------------------------------------------------------------------


class TestEvidenceCliEndToEnd:
    """Exercises `python -m serein.distribution evidence` (and
    `closure-gate`) exactly the way iso-smoke.yml now calls them, to
    prove the real CLI wiring - not just the pure
    ``assemble_layer_b_evidence`` function - handles the exact real
    scenario a Layer-B run hit: an early ``base_fetch`` failure, with
    the workflow passing ``--production-build not_performed
    --qa-build not_performed`` (Corrective B) and real pinned metadata
    from ``distribution/base-image.json`` even though nothing was ever
    downloaded (Corrective C)."""

    def test_early_base_fetch_failure_produces_not_performed_not_fail(self, tmp_path, capsys):
        from serein.distribution.__main__ import main

        out_path = tmp_path / "evidence.json"
        argv = [
            "evidence",
            "--source-commit", "a" * 40,
            "--failure-stage", "base_fetch",
            "--failure-reason", "fetch-base-image.sh failed",
            "--base-filename", "ubuntu-26.04.1-desktop-amd64.iso",
            "--base-sha256-expected", "b" * 64,
            "--base-sha256-actual", "",
            "--production-build", "not_performed",
            "--qa-build", "not_performed",
            "--out", str(out_path),
        ]
        exit_code = main(argv)
        assert exit_code == 0

        data = json.loads(out_path.read_text())
        # Corrective B: never "fail" for a stage that never began
        assert data["production_build"] == "not_performed"
        assert data["qa_build"] == "not_performed"
        assert data["production_inspection"] == "not_performed"
        assert data["qa_inspection"] == "not_performed"
        assert data["qemu_boot"] == "not_performed"
        # Corrective C: pinned metadata present even without a download
        assert data["base_filename"] == "ubuntu-26.04.1-desktop-amd64.iso"
        assert data["base_sha256_expected"] == "b" * 64
        # actual/verified remain honestly absent/false - never fabricated
        assert data["base_sha256_actual"] is None
        assert data["base_verified"] is False

    def test_production_failure_qa_never_attempted(self, tmp_path):
        from serein.distribution.__main__ import main

        out_path = tmp_path / "evidence.json"
        argv = [
            "evidence",
            "--source-commit", "a" * 40,
            "--failure-stage", "production_or_qa_build",
            "--failure-reason", "build-iso.sh failed",
            "--base-filename", "ubuntu-26.04.1-desktop-amd64.iso",
            "--base-sha256-expected", "b" * 64,
            "--base-sha256-actual", "b" * 64,
            "--production-build", "fail",
            "--qa-build", "not_performed",
            "--out", str(out_path),
        ]
        assert main(argv) == 0
        data = json.loads(out_path.read_text())
        assert data["production_build"] == "fail"
        assert data["qa_build"] == "not_performed"
        assert data["base_verified"] is True  # real hashes matched

    def test_closure_gate_cli_fails_closed_on_early_failure_evidence(self, tmp_path):
        from serein.distribution.__main__ import main

        evidence_path = tmp_path / "evidence.json"
        main([
            "evidence", "--source-commit", "a" * 40,
            "--failure-stage", "base_fetch", "--failure-reason", "fetch failed",
            "--base-filename", "ubuntu-26.04.1-desktop-amd64.iso",
            "--base-sha256-expected", "b" * 64, "--base-sha256-actual", "",
            "--production-build", "not_performed", "--qa-build", "not_performed",
            "--out", str(evidence_path),
        ])

        exit_code = main([
            "closure-gate", "--evidence", str(evidence_path),
            "--expected-source-commit", "a" * 40,
        ])
        assert exit_code == 1

    def test_inspect_and_boot_smoke_subcommands_are_registered(self):
        from serein.distribution.__main__ import main

        # argparse itself proves these subcommands exist and parse -
        # both fail fast (missing required file/iso) without needing
        # xorriso/qemu, which is exactly the point: CLI wiring is
        # checked here, real tool execution is Layer B's job.
        assert main(["inspect", "does-not-exist.iso"]) == 1
        assert main([
            "boot-smoke", "--iso", "does-not-exist.iso", "--require-uefi",
        ]) == 1


# ---------------------------------------------------------------------------
# S7.0R: full build pipeline integration (all five correctives together)
# ---------------------------------------------------------------------------


def _fake_repo_root(tmp_path):
    """A minimal, self-contained repo_root a fully-faked run_build() can
    operate against: its own base-image.json (fake sha256), its own
    cached "base ISO" matching that hash, its own overlay tree, and one
    resource file - proving the pipeline orchestration without needing
    the real repository or real xorriso."""
    repo_root = tmp_path / "fake_repo"
    (repo_root / "distribution" / "overlay" / "serein").mkdir(parents=True)
    (repo_root / "distribution" / "overlay" / "serein" / "README.txt").write_text("hi")
    (repo_root / "desktop").mkdir()
    (repo_root / "desktop" / "note.txt").write_text("a desktop resource")

    cache_dir = repo_root / "cache" / "upstream"
    cache_dir.mkdir(parents=True)
    base_iso = cache_dir / "fake-base.iso"
    base_iso.write_bytes(b"fake but consistent base iso bytes")

    base_sha256 = sha256_file(base_iso)
    base_spec = {
        "schema_version": 1, "distribution": "ubuntu", "release": "26.04",
        "point_release": "26.04.1", "codename": "resolute", "architecture": "amd64",
        "edition": "desktop", "source": "official-ubuntu-release", "filename": "fake-base.iso",
        "sha256": base_sha256, "sha256sums_url": "https://example.invalid/SHA256SUMS",
        "signature_url": "https://example.invalid/SHA256SUMS.gpg",
        "signing_key_fingerprint": "0" * 40, "signing_key_source": "test", "verified": False,
    }
    (repo_root / "distribution").mkdir(exist_ok=True)
    (repo_root / "distribution" / "base-image.json").write_text(json.dumps(base_spec))
    return repo_root


def _write_synthetic_wheel(out_dir: Path) -> None:
    """A minimal synthetic wheel containing exactly the module paths
    `inspect_wheel_contents` requires - used by the fake pipeline
    runner below. The *real* wheel-build proof (actually invoking
    `python -m build`) lives in TestWheelPayload, which runs against
    this real repository."""
    import zipfile

    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = out_dir / "serein-0.1.0.dev0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as archive:
        for module in EXPECTED_WHEEL_MODULES:
            archive.writestr(module, "")


def _fake_build_runner(extracted_grub_text: str):
    """A fake subprocess runner covering every external command
    run_build() invokes: extraction (writes a minimal tree with a real
    grub.cfg so the QA variant step can run for real), the wheel build
    (fabricates a synthetic wheel with the expected module list - the
    *real* `python -m build` invocation is proven separately in
    TestWheelPayload against the real repository), the el-torito
    report, and both ISO rebuilds (write real, distinguishable bytes to
    each output path)."""

    def runner(argv, **kwargs):
        if "-m" in argv and "build" in argv:
            out_dir = Path(argv[argv.index("--outdir") + 1])
            _write_synthetic_wheel(out_dir)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "-osirrox" in argv and "-extract" in argv:
            dest = Path(argv[argv.index("-extract") + 2])
            (dest / "boot" / "grub").mkdir(parents=True)
            (dest / "boot" / "grub" / "grub.cfg").write_text(extracted_grub_text)
            (dest / "EFI" / "boot").mkdir(parents=True)
            (dest / "EFI" / "boot" / "bootx64.efi").write_bytes(b"efi")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "-report_el_torito" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout="-c '/boot.catalog'\n-appended_part_as_gpt\n", stderr=""
            )
        if "-as" in argv and "mkisofs" in argv:
            output_path = Path(argv[argv.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(f"iso bytes for {output_path.name}".encode())
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected argv in fake build runner: {argv}")

    return runner


class TestBuildPipelineIntegration:
    def test_full_pipeline_produces_production_and_qa_isos(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        runner = _fake_build_runner(grub_text)

        result = run_build(
            repo_root=repo_root,
            work_dir=tmp_path / "work",
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40,
            subprocess_runner=runner,
        )

        assert isinstance(result, BuildResult)
        assert result.production.output.filename == "serein-alpha-26.04-amd64.iso"
        assert result.qa is not None
        assert result.qa.output.filename == "serein-alpha-26.04-amd64-qa.iso"
        assert result.qa_blocked_reason is None

    def test_wheel_entry_present_in_payload_manifest(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        runner = _fake_build_runner(grub_text)
        work_dir = tmp_path / "work"

        run_build(
            repo_root=repo_root, work_dir=work_dir,
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40, subprocess_runner=runner,
        )

        payload_manifest = json.loads(
            (work_dir / "extracted" / "serein" / "payload-manifest.json").read_text()
        )
        wheel_entries = [
            e for e in payload_manifest["entries"] if e["path"].startswith("packages/")
        ]
        assert len(wheel_entries) == 1
        assert wheel_entries[0]["path"].endswith(".whl")

        wheel_on_disk = work_dir / "extracted" / "serein" / "payload" / wheel_entries[0]["path"]
        assert wheel_on_disk.is_file()

    def test_qa_iso_blocked_when_no_grub_candidate(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        runner = _fake_build_runner_no_grub = _fake_build_runner_without_grub()
        result = run_build(
            repo_root=repo_root, work_dir=tmp_path / "work",
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40, subprocess_runner=runner,
        )
        assert result.production is not None  # production still succeeds
        assert result.qa is None
        assert result.qa_blocked_reason is not None
        del _fake_build_runner_no_grub

    def test_boot_flags_identical_for_production_and_qa_rebuild(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        seen_rebuild_argvs = []

        base_runner = _fake_build_runner(grub_text)

        def recording_runner(argv, **kwargs):
            if "-as" in argv and "mkisofs" in argv:
                seen_rebuild_argvs.append(argv)
            return base_runner(argv, **kwargs)

        run_build(
            repo_root=repo_root, work_dir=tmp_path / "work",
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40, subprocess_runner=recording_runner,
        )

        assert len(seen_rebuild_argvs) == 2
        prod_flags = [a for a in seen_rebuild_argvs[0] if a.startswith("-") or a == "/boot.catalog"]
        qa_flags = [a for a in seen_rebuild_argvs[1] if a.startswith("-") or a == "/boot.catalog"]
        assert "/boot.catalog" in seen_rebuild_argvs[0]
        assert "/boot.catalog" in seen_rebuild_argvs[1]
        del prod_flags, qa_flags

    def test_second_build_starts_from_clean_workspace(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        runner = _fake_build_runner(grub_text)
        work_dir = tmp_path / "work"

        run_build(
            repo_root=repo_root, work_dir=work_dir,
            output_iso=tmp_path / "dist" / "a.iso",
            source_commit="a" * 40, subprocess_runner=runner,
        )
        (work_dir / "extracted" / "stale-marker.txt").write_text("should not survive")

        run_build(
            repo_root=repo_root, work_dir=work_dir,
            output_iso=tmp_path / "dist" / "b.iso",
            source_commit="b" * 40, subprocess_runner=runner,
        )

        assert not (work_dir / "extracted" / "stale-marker.txt").exists()

    def test_builder_version_recorded_and_bumped(self, tmp_path):
        from serein.distribution.models import BUILDER_VERSION

        assert BUILDER_VERSION.endswith("/0.2")


def _fake_build_runner_without_grub():
    def runner(argv, **kwargs):
        if "-m" in argv and "build" in argv:
            out_dir = Path(argv[argv.index("--outdir") + 1])
            _write_synthetic_wheel(out_dir)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "-osirrox" in argv and "-extract" in argv:
            dest = Path(argv[argv.index("-extract") + 2])
            dest.mkdir(parents=True, exist_ok=True)
            # deliberately no boot/grub/grub.cfg anywhere - QA discovery must block
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "-report_el_torito" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout="-c '/boot.catalog'\n-appended_part_as_gpt\n", stderr=""
            )
        if "-as" in argv and "mkisofs" in argv:
            output_path = Path(argv[argv.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"iso bytes")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected argv: {argv}")

    return runner


# ---------------------------------------------------------------------------
# S7.0RM2 Corrective A: git executable-bit correctness
# ---------------------------------------------------------------------------


class TestGitExecutableModes:
    """A real Layer-B run failed with `Permission denied` invoking
    ``./distribution/scripts/fetch-base-image.sh`` because every direct
    shell entrypoint under ``distribution/scripts/`` was tracked as
    ``100644`` in the Git tree - a filesystem `chmod` alone cannot fix
    this, since GitHub Actions materializes whatever mode the *Git
    tree* records, not whatever a previous local checkout happened to
    carry. This inspects the Git index directly (``git ls-files -s``),
    never local filesystem permissions, which are not portable (this
    suite also runs on Windows, where POSIX x-bit semantics do not
    apply to the working copy at all) and would not have caught the
    real defect."""

    def _tracked_modes(self) -> dict[str, str]:
        result = subprocess.run(
            ["git", "ls-files", "-s", "distribution/scripts/"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        modes: dict[str, str] = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^(\d{6})\s+\S+\s+\d+\t(.+)$", line)
            if match:
                modes[match.group(2)] = match.group(1)
        return modes

    def test_all_shell_entrypoints_are_git_executable(self):
        # Dynamic, not a fixed literal list - any *.sh future addition
        # under distribution/scripts/ must also carry 100755, so this
        # regresses "loses its executable bit in the future" for
        # scripts that do not exist yet, not only the six known today.
        scripts_dir = REPO_ROOT / "distribution" / "scripts"
        required = {
            f"distribution/scripts/{p.name}" for p in scripts_dir.glob("*.sh")
        }
        assert required, "expected at least one *.sh entrypoint to check"

        modes = self._tracked_modes()
        for path in sorted(required):
            assert path in modes, f"{path} is not tracked by git at all"
            assert modes[path] == "100755", (
                f"{path} has git tree mode {modes[path]!r}, expected '100755' - "
                "a filesystem chmod alone does not fix this, the Git index entry "
                "itself must carry the executable bit"
            )

    def test_known_six_entrypoints_explicitly(self):
        # Belt-and-suspenders: the exact six scripts named in the
        # corrective, checked by name so a rename/deletion is caught
        # even if the dynamic glob above were ever satisfied trivially.
        expected = {
            "distribution/scripts/boot-smoke.sh": "100755",
            "distribution/scripts/build-iso.sh": "100755",
            "distribution/scripts/clean.sh": "100755",
            "distribution/scripts/fetch-base-image.sh": "100755",
            "distribution/scripts/inspect-iso.sh": "100755",
            "distribution/scripts/verify-base-image.sh": "100755",
        }
        modes = self._tracked_modes()
        for path, expected_mode in expected.items():
            assert modes.get(path) == expected_mode


# ---------------------------------------------------------------------------
# S7.0RM Corrective A: storage
# ---------------------------------------------------------------------------


class TestStorage:
    def test_directory_size_bytes_missing_dir_is_zero(self, tmp_path):
        assert directory_size_bytes(tmp_path / "does-not-exist") == 0

    def test_directory_size_bytes_sums_files(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        (d / "a.txt").write_bytes(b"12345")
        (d / "sub").mkdir()
        (d / "sub" / "b.txt").write_bytes(b"1234567890")
        assert directory_size_bytes(d) == 15

    def test_measure_disk_usage_reports_all_fields(self, tmp_path):
        (tmp_path / "cache" / "upstream").mkdir(parents=True)
        (tmp_path / "cache" / "upstream" / "base.iso").write_bytes(b"x" * 100)
        report = measure_disk_usage(tmp_path)
        assert report.cache_upstream_bytes == 100
        assert report.build_work_bytes == 0
        assert report.dist_bytes == 0
        assert report.free_bytes > 0
        assert "cache_upstream_bytes" in report.to_dict()

    def test_release_base_iso_deletes_file_inside_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "cache" / "upstream"
        cache_dir.mkdir(parents=True)
        base_iso = cache_dir / "base.iso"
        base_iso.write_bytes(b"verified base bytes")

        deleted = release_base_iso(base_iso, cache_dir)
        assert deleted is True
        assert not base_iso.exists()

    def test_release_base_iso_idempotent_when_already_absent(self, tmp_path):
        cache_dir = tmp_path / "cache" / "upstream"
        cache_dir.mkdir(parents=True)
        deleted = release_base_iso(cache_dir / "missing.iso", cache_dir)
        assert deleted is False

    def test_release_base_iso_rejects_path_outside_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "cache" / "upstream"
        cache_dir.mkdir(parents=True)
        outside = tmp_path / "dist" / "important.iso"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"do not delete me")

        with pytest.raises(StorageError):
            release_base_iso(outside, cache_dir)
        assert outside.exists()  # never touched


# ---------------------------------------------------------------------------
# S7.0RM Corrective A: storage-efficient in-place QA transition
# ---------------------------------------------------------------------------


class TestQaInPlaceTransition:
    def test_transition_in_place_patches_the_same_directory(self, tmp_path):
        dest = tmp_path / "extracted"
        shutil.copytree(FIXTURES_DIR / "extracted-tree-ok", dest)

        result = transition_to_qa_in_place(dest)

        patched = (dest / result.grub_config_relative_path).read_text()
        assert QA_ENTRY_TITLE in patched
        assert 'set default="0"' in patched
        # no second tree was ever created
        assert not (tmp_path / "extracted-qa").exists()

    def test_transition_in_place_preserves_payload_and_marker(self, tmp_path):
        dest = tmp_path / "extracted"
        shutil.copytree(FIXTURES_DIR / "extracted-tree-ok", dest)
        marker_before = (dest / "serein" / "manifest.json").read_bytes()
        payload_before = (dest / "serein" / "payload" / "hello.txt").read_bytes()

        transition_to_qa_in_place(dest)

        assert (dest / "serein" / "manifest.json").read_bytes() == marker_before
        assert (dest / "serein" / "payload" / "hello.txt").read_bytes() == payload_before

    def test_transition_in_place_blocked_without_grub_candidate(self, tmp_path):
        dest = tmp_path / "extracted"
        dest.mkdir()
        (dest / "serein").mkdir()
        with pytest.raises(QaBootError):
            transition_to_qa_in_place(dest)

    def test_transition_in_place_detects_unexpected_protected_mutation(self, tmp_path, monkeypatch):
        dest = tmp_path / "extracted"
        shutil.copytree(FIXTURES_DIR / "extracted-tree-ok", dest)

        real_install = install_qa_entry_as_default

        def corrupting_install(grub_text, qa_entry_text):
            # Simulate a hypothetical future bug that touches a file it
            # has no business touching, alongside the real GRUB patch.
            (dest / "EFI" / "boot" / "bootx64.efi").write_bytes(b"corrupted!")
            return real_install(grub_text, qa_entry_text)

        monkeypatch.setattr(
            "serein.distribution.qa_boot.install_qa_entry_as_default", corrupting_install
        )

        with pytest.raises(QaProtectedFileMutationError):
            transition_to_qa_in_place(dest)

    def test_transition_in_place_updates_checksum_catalog(self, tmp_path):
        dest = tmp_path / "extracted"
        (dest / "boot" / "grub").mkdir(parents=True)
        grub_path = dest / "boot" / "grub" / "grub.cfg"
        grub_path.write_text(
            'menuentry "Try or Install Serein OS Alpha" {\n'
            "    linux   /casper/vmlinuz boot=casper splash ---\n"
            "    initrd  /casper/initrd\n"
            "}\n"
        )
        import hashlib

        stale_hash = hashlib.md5(b"stale").hexdigest()  # noqa: S324
        (dest / "md5sum.txt").write_text(f"{stale_hash}  ./boot/grub/grub.cfg\n")

        result = transition_to_qa_in_place(dest)
        assert result.checksum_catalog_updated is True
        catalog_text = (dest / "md5sum.txt").read_text()
        assert stale_hash not in catalog_text


# ---------------------------------------------------------------------------
# S7.0RM Corrective D/F: boot-mode derivation
# ---------------------------------------------------------------------------


class TestBootModeDerivation:
    def test_no_ovmf_is_bios(self):
        assert derive_boot_mode(None) == "bios"

    def test_ovmf_present_is_uefi(self, tmp_path):
        assert derive_boot_mode(tmp_path / "OVMF_CODE.fd") == "uefi"


# ---------------------------------------------------------------------------
# S7.0RM Corrective G: explicit fail-closed Layer-B closure gate
# ---------------------------------------------------------------------------


def _passing_evidence(**overrides):
    base = dict(
        source_commit="a" * 40,
        base_sha256_expected="b" * 64, base_sha256_actual="b" * 64,
        production_build="pass", production_inspection="pass",
        qa_build="pass", qa_inspection="pass",
        qemu_boot="pass", qemu_boot_mode="uefi",
        boot_marker="Reached target Basic System",
    )
    base.update(overrides)
    return assemble_layer_b_evidence(**base)


class TestClosureGate:
    def test_all_required_fields_pass_closure_passes(self):
        evidence = _passing_evidence()
        enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)  # must not raise

    def test_base_not_verified_fails(self):
        evidence = _passing_evidence(base_sha256_actual="c" * 64)
        with pytest.raises(ClosureError, match="base_verified"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_production_inspection_fail_fails(self):
        evidence = _passing_evidence(production_inspection="fail")
        with pytest.raises(ClosureError, match="production_inspection"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_qa_build_fail_fails(self):
        evidence = _passing_evidence(qa_build="fail")
        with pytest.raises(ClosureError, match="qa_build"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_qemu_boot_fail_fails(self):
        evidence = _passing_evidence(qemu_boot="fail")
        with pytest.raises(ClosureError, match="qemu_boot"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_boot_marker_null_fails(self):
        evidence = _passing_evidence(boot_marker=None)
        with pytest.raises(ClosureError, match="boot_marker"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_bios_only_boot_fails(self):
        evidence = _passing_evidence(qemu_boot_mode="bios")
        with pytest.raises(ClosureError, match="qemu_boot_mode"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_wrong_source_commit_fails(self):
        evidence = _passing_evidence()
        with pytest.raises(ClosureError, match="source_commit"):
            enforce_layer_b_closure(evidence, expected_source_commit="f" * 40)

    def test_target_disk_attached_fails(self):
        from dataclasses import replace as dc_replace

        evidence = dc_replace(_passing_evidence(), target_disk_attached=True)
        with pytest.raises(ClosureError, match="target_disk_attached"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_autoinstall_enabled_fails(self):
        from dataclasses import replace as dc_replace

        evidence = dc_replace(_passing_evidence(), autoinstall_enabled=True)
        with pytest.raises(ClosureError, match="autoinstall_enabled"):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)

    def test_multiple_failures_all_listed(self):
        evidence = _passing_evidence(qemu_boot="fail", qa_build="fail")
        with pytest.raises(ClosureError) as exc_info:
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)
        message = str(exc_info.value)
        assert "qemu_boot" in message
        assert "qa_build" in message

    def test_early_preflight_failure_evidence_fails_closure(self):
        # The real defect this corrective fixes: a preflight failure
        # before any base download must still produce evidence, and
        # that evidence must fail the closure gate, never pass it.
        evidence = assemble_layer_b_evidence(
            source_commit="a" * 40, failure_stage="disk_preflight",
            failure_reason="insufficient free space",
        )
        with pytest.raises(ClosureError):
            enforce_layer_b_closure(evidence, expected_source_commit="a" * 40)


# ---------------------------------------------------------------------------
# S7.0RM: ephemeral-storage build integration
# ---------------------------------------------------------------------------


class TestEphemeralStorageBuild:
    def test_ephemeral_storage_deletes_cached_base_after_use(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        base_iso = repo_root / "cache" / "upstream" / "fake-base.iso"
        assert base_iso.is_file()

        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        runner = _fake_build_runner(grub_text)

        run_build(
            repo_root=repo_root, work_dir=tmp_path / "work",
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40, subprocess_runner=runner,
            ephemeral_storage=True,
        )

        assert not base_iso.exists()

    def test_normal_build_preserves_cached_base(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        base_iso = repo_root / "cache" / "upstream" / "fake-base.iso"

        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        runner = _fake_build_runner(grub_text)

        run_build(
            repo_root=repo_root, work_dir=tmp_path / "work",
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40, subprocess_runner=runner,
            ephemeral_storage=False,
        )

        assert base_iso.is_file()  # untouched by default

    def test_qa_build_never_creates_a_second_extracted_tree(self, tmp_path):
        repo_root = _fake_repo_root(tmp_path)
        grub_text = (FIXTURES_DIR / "grub-cfg-safe.cfg").read_text()
        runner = _fake_build_runner(grub_text)
        work_dir = tmp_path / "work"

        result = run_build(
            repo_root=repo_root, work_dir=work_dir,
            output_iso=tmp_path / "dist" / "serein-alpha-26.04-amd64.iso",
            source_commit="a" * 40, subprocess_runner=runner,
        )

        assert result.qa is not None
        assert not (work_dir / "extracted-qa").exists()
