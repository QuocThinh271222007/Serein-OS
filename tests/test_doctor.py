"""Doctor check tests.

OS-family/architecture checks reflect the real interpreter (there is
nothing else to check them against), so they are exercised via
``monkeypatch`` on ``platform`` rather than by asserting a status that
would depend on whatever OS happens to run the test suite — required by
the "no test depends on host state" rule.
"""

from __future__ import annotations

from serein.doctor import checks as doctor_checks
from serein.doctor.models import CheckResult, CheckStatus, DoctorReport


class TestOSFamilyCheck:
    def test_pass_on_linux(self, monkeypatch, host_root):
        monkeypatch.setattr(doctor_checks.platform, "system", lambda: "Linux")
        result = doctor_checks._check_os_family(host_root("amd_desktop"))
        assert result.status is CheckStatus.PASS

    def test_fail_on_non_linux(self, monkeypatch, host_root):
        monkeypatch.setattr(doctor_checks.platform, "system", lambda: "Windows")
        result = doctor_checks._check_os_family(host_root("amd_desktop"))
        assert result.status is CheckStatus.FAIL


class TestArchitectureCheck:
    def test_pass_on_x86_64(self, monkeypatch, host_root):
        monkeypatch.setattr(doctor_checks.platform, "machine", lambda: "x86_64")
        result = doctor_checks._check_architecture(host_root("amd_desktop"))
        assert result.status is CheckStatus.PASS

    def test_warn_on_other_architecture(self, monkeypatch, host_root):
        monkeypatch.setattr(doctor_checks.platform, "machine", lambda: "aarch64")
        result = doctor_checks._check_architecture(host_root("amd_desktop"))
        assert result.status is CheckStatus.WARN


class TestProcSysAvailability:
    def test_present_in_fixture_passes(self, host_root):
        root = host_root("amd_desktop")
        assert doctor_checks._check_proc_available(root).status is CheckStatus.PASS
        assert doctor_checks._check_sys_available(root).status is CheckStatus.PASS

    def test_absent_in_missing_data_warns(self, host_root):
        root = host_root("missing_data")
        assert doctor_checks._check_proc_available(root).status is CheckStatus.WARN
        assert doctor_checks._check_sys_available(root).status is CheckStatus.WARN


class TestSchemaValidityCheck:
    def test_passes_against_real_repository_schemas(self, host_root):
        result = doctor_checks._check_schema_validity(host_root("amd_desktop"))
        assert result.status is CheckStatus.PASS


class TestHardwareProbeCheck:
    def test_passes_for_every_fixture_scenario(self, host_root):
        for scenario in ("amd_desktop", "missing_data", "wsl_environment"):
            result = doctor_checks._check_hardware_probe(host_root(scenario))
            assert result.status is CheckStatus.PASS


class TestRunChecks:
    def test_returns_one_result_per_registered_check(self, host_root):
        report = doctor_checks.run_checks(host_root("amd_desktop"))
        assert len(report.checks) == len(doctor_checks._ALL_CHECKS)

    def test_json_shape(self, host_root):
        report = doctor_checks.run_checks(host_root("amd_desktop"))
        data = report.to_dict()
        assert data["schema_version"] == 1
        assert set(data["summary"]) == {"PASS", "WARN", "FAIL", "SKIP"}
        assert len(data["checks"]) == len(report.checks)


class TestExitCodeSemantics:
    def _report(self, statuses: list[CheckStatus]) -> DoctorReport:
        return DoctorReport(
            schema_version=1,
            checks=[
                CheckResult(id=f"c{i}", title="t", status=status, detail="d")
                for i, status in enumerate(statuses)
            ],
        )

    def test_all_pass_exits_zero(self):
        assert self._report([CheckStatus.PASS, CheckStatus.PASS]).exit_code == 0

    def test_warn_and_skip_do_not_affect_exit_code(self):
        report = self._report([CheckStatus.PASS, CheckStatus.WARN, CheckStatus.SKIP])
        assert report.exit_code == 0

    def test_any_fail_exits_one(self):
        report = self._report([CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.WARN])
        assert report.exit_code == 1

    def test_empty_checks_exits_zero(self):
        assert self._report([]).exit_code == 0
