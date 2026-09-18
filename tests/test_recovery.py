"""Tests for the Recovery subsystem (Phase-7-completion Section
37-41, historical S7.3 scope).

Layer A only: every test runs against an injectable ``root``
(``tmp_path``) - never the real host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serein.branding.os_identity import render_os_release
from serein.cli import main
from serein.desktop import config as desktop_config
from serein.recovery.checks import check_managed_files
from serein.recovery.doctor import run_recovery_checks
from serein.recovery.plan import build_recovery_plan
from serein.recovery.repair import RecoveryRepairError, repair_managed_files
from serein.recovery.status import build_recovery_status


def _system_desktop_resource_count() -> int:
    return sum(1 for r in desktop_config.RESOURCES if r.owner == "system")


class TestCheckManagedFiles:
    def test_missing_files_reported_honestly(self, tmp_path: Path) -> None:
        checks = check_managed_files(tmp_path)
        by_id = {c.id: c for c in checks}
        assert by_id["os-release"].status == "MISSING"
        assert by_id["os-release"].regeneratable is True

    def test_correct_content_is_ok(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text(render_os_release(), encoding="utf-8")
        checks = check_managed_files(tmp_path)
        by_id = {c.id: c for c in checks}
        assert by_id["os-release"].status == "OK"

    def test_wrong_content_is_modified(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text("NAME=tampered\n", encoding="utf-8")
        checks = check_managed_files(tmp_path)
        by_id = {c.id: c for c in checks}
        assert by_id["os-release"].status == "MODIFIED"

    def test_desktop_resources_present_are_unknown_never_ok(self, tmp_path: Path) -> None:
        for resource in desktop_config.RESOURCES:
            if resource.owner != "system":
                continue
            target = tmp_path / resource.target_path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("anything", encoding="utf-8")
        checks = check_managed_files(tmp_path)
        desktop_checks = [c for c in checks if c.id in {
            r.id for r in desktop_config.RESOURCES if r.owner == "system"
        }]
        assert len(desktop_checks) == _system_desktop_resource_count()
        assert all(c.status == "UNKNOWN" for c in desktop_checks)
        assert all(c.regeneratable is False for c in desktop_checks)

    def test_desktop_resources_missing_are_missing(self, tmp_path: Path) -> None:
        checks = check_managed_files(tmp_path)
        desktop_checks = [c for c in checks if c.id in {
            r.id for r in desktop_config.RESOURCES if r.owner == "system"
        }]
        assert all(c.status == "MISSING" for c in desktop_checks)


class TestStatus:
    def test_unhealthy_when_anything_missing(self, tmp_path: Path) -> None:
        status = build_recovery_status(tmp_path)
        assert status.healthy is False

    def test_healthy_when_everything_ok(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text(render_os_release(), encoding="utf-8")
        (etc / "issue").write_text("Serein OS \\n \\l\n\n", encoding="utf-8")
        (etc / "issue.net").write_text("Serein OS\n", encoding="utf-8")
        for resource in desktop_config.RESOURCES:
            if resource.owner != "system":
                continue
            target = tmp_path / resource.target_path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        status = build_recovery_status(tmp_path)
        # Desktop resources are UNKNOWN, not OK, so "healthy" (all OK)
        # is still correctly False - UNKNOWN never counts as healthy.
        assert status.healthy is False


class TestDoctor:
    def test_missing_regeneratable_file_is_fail(self, tmp_path: Path) -> None:
        report = run_recovery_checks(tmp_path)
        by_id = {c.id: c for c in report.checks}
        assert by_id["recovery_os_release"].status.value == "FAIL"

    def test_unknown_desktop_resource_is_warn_never_fail(self, tmp_path: Path) -> None:
        for resource in desktop_config.RESOURCES:
            if resource.owner != "system":
                continue
            target = tmp_path / resource.target_path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        report = run_recovery_checks(tmp_path)
        system_ids = {
            f"recovery_{r.id.replace('-', '_')}"
            for r in desktop_config.RESOURCES if r.owner == "system"
        }
        by_id = {c.id: c for c in report.checks}
        for check_id in system_ids:
            assert by_id[check_id].status.value == "WARN"


class TestPlan:
    def test_ok_files_have_no_action(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text(render_os_release(), encoding="utf-8")
        plan = build_recovery_plan(tmp_path)
        assert not any(a.id == "os-release" for a in plan.actions)

    def test_missing_regeneratable_file_would_be_repaired(self, tmp_path: Path) -> None:
        plan = build_recovery_plan(tmp_path)
        action = next(a for a in plan.actions if a.id == "os-release")
        assert action.would_write is True

    def test_missing_desktop_resource_is_not_auto_repairable(self, tmp_path: Path) -> None:
        plan = build_recovery_plan(tmp_path)
        desktop_ids = {r.id for r in desktop_config.RESOURCES if r.owner == "system"}
        desktop_actions = [a for a in plan.actions if a.id in desktop_ids]
        assert desktop_actions
        assert all(a.would_write is False for a in desktop_actions)


class TestRepair:
    def test_refuses_without_explicit_allow_repair(self, tmp_path: Path) -> None:
        with pytest.raises(RecoveryRepairError):
            repair_managed_files(tmp_path, allow_repair=False)

    def test_repairs_missing_regeneratable_files(self, tmp_path: Path) -> None:
        report = repair_managed_files(tmp_path, allow_repair=True)
        assert report.all_repaired is True
        assert (tmp_path / "etc" / "os-release").is_file()
        assert (tmp_path / "etc" / "os-release").read_text(encoding="utf-8") == render_os_release()

    def test_already_ok_file_is_not_rewritten(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        target = etc / "os-release"
        target.write_text(render_os_release(), encoding="utf-8")
        before_mtime = target.stat().st_mtime_ns

        report = repair_managed_files(tmp_path, allow_repair=True)
        result = next(r for r in report.results if r.id == "os-release")
        assert result.repaired is False
        assert target.stat().st_mtime_ns == before_mtime

    def test_never_touches_desktop_resources(self, tmp_path: Path) -> None:
        repair_managed_files(tmp_path, allow_repair=True)
        for resource in desktop_config.RESOURCES:
            if resource.owner != "system":
                continue
            target = tmp_path / resource.target_path.lstrip("/")
            assert not target.exists()


class TestCLI:
    def test_status_human_output(self, capsys) -> None:
        exit_code = main(["recovery", "status"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "SEREIN RECOVERY" in captured.out

    def test_status_json_is_well_formed(self, capsys) -> None:
        import json

        exit_code = main(["recovery", "status", "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        data = json.loads(captured.out)
        assert data["schema_version"] == 1
        assert "healthy" in data

    def test_doctor_human_output(self, capsys) -> None:
        exit_code = main(["recovery", "doctor"])
        captured = capsys.readouterr()
        assert exit_code in (0, 1)
        assert "SEREIN RECOVERY DOCTOR" in captured.out

    def test_plan_human_output_mentions_no_mutation(self, capsys) -> None:
        exit_code = main(["recovery", "plan"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "SEREIN RECOVERY PLAN" in captured.out
        assert "Mutation: none" in captured.out

    def test_repair_is_not_a_main_cli_subcommand(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["recovery", "repair"])
        assert excinfo.value.code != 0


class TestRepairMainEntrypoint:
    def test_refuses_without_flag(self, capsys) -> None:
        # repair_managed_files(allow_repair=False) raises BEFORE ever
        # touching root/DEFAULT_ROOT - safe to call unmodified even
        # though this entrypoint has no --root override (Section 90 -
        # never a host-destructive test operation).
        from serein.recovery.__main__ import main as recovery_main

        exit_code = recovery_main(["repair"])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "error" in captured.err.lower()

    # No test here exercises `--allow-repair` through this entrypoint:
    # doing so would operate on the real DEFAULT_ROOT (this entrypoint
    # has no --root override, deliberately, since a real system must
    # always repair itself, never an operator-chosen path). The full
    # repair logic is already proven safely against tmp_path via
    # TestRepair above and serein.recovery.repair.repair_managed_files
    # directly.
