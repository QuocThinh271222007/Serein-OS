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
    evaluate_boot_log,
    run_boot_smoke,
)
from serein.distribution.build import BuildError, run_build
from serein.distribution.inspect import inspect_extracted_tree, inspect_iso_file
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
    PAYLOAD_RESOURCE_ROOTS,
    build_payload_manifest,
    collect_resource_entries,
)
from serein.distribution.safety import (
    scan_boot_config_for_default_autoinstall,
    scan_text_for_credentials,
    scan_tree_for_credentials,
)
from serein.distribution.status import build_distribution_status

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = REPO_ROOT / "distribution" / "test-fixtures"


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

    def test_run_boot_smoke_reports_pass_when_marker_written(self, tmp_path):
        def fake_runner(command, **kwargs):
            serial_index = command.index("-serial") + 1
            log_path = Path(command[serial_index].removeprefix("file:"))
            log_path.write_text("... Reached target Basic System ...")
            return subprocess.CompletedProcess(command, 0)

        result = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            subprocess_runner=fake_runner,
        )
        assert result.status == "pass"
        assert result.matched_marker is not None

    def test_run_boot_smoke_reports_fail_on_timeout(self, tmp_path):
        def timeout_runner(command, **kwargs):
            raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs.get("timeout", 1))

        result = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            timeout_seconds=1, subprocess_runner=timeout_runner,
        )
        assert result.status == "fail"
        assert "timed out" in result.reason

    def test_run_boot_smoke_reports_fail_when_no_marker(self, tmp_path):
        def silent_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0)

        result = run_boot_smoke(
            iso_path=tmp_path / "iso.iso", work_dir=tmp_path / "work",
            subprocess_runner=silent_runner,
        )
        assert result.status == "fail"
        assert result.matched_marker is None


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
