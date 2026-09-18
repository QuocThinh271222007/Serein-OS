"""CLI invocation tests. Runs against the real host (all commands are
read-only and safe to run anywhere, including CI and a developer machine).
"""

from __future__ import annotations

import json

import pytest

from serein import __version__
from serein.cli import main


def test_version_prints_version_and_exits_zero(capsys) -> None:
    exit_code = main(["version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == __version__


def test_status_runs_and_exits_zero(capsys) -> None:
    exit_code = main(["status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN" in captured.out
    assert "Current profile:" in captured.out


def test_status_never_prints_hostname_or_username(capsys, monkeypatch) -> None:
    import getpass
    import socket

    monkeypatch.setenv("USER", "should-not-appear")
    exit_code = main(["status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert socket.gethostname() not in captured.out
    assert getpass.getuser() not in captured.out


def test_doctor_human_output_exits_zero_or_one(capsys) -> None:
    exit_code = main(["doctor"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    assert "SEREIN DOCTOR" in captured.out
    assert "Summary:" in captured.out


def test_doctor_json_is_well_formed(capsys) -> None:
    exit_code = main(["doctor", "--json"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert "checks" in data


def test_hardware_probe_human_output(capsys) -> None:
    exit_code = main(["hardware", "probe"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN HARDWARE PROBE" in captured.out


def test_hardware_probe_json_is_well_formed(capsys) -> None:
    exit_code = main(["hardware", "probe", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert "cpu" in data


def test_profile_list_human_output(capsys) -> None:
    exit_code = main(["profile", "list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "core" in captured.out
    assert "not implemented in S0" in captured.out


def test_profile_list_json_is_well_formed(capsys) -> None:
    exit_code = main(["profile", "list", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out)
    ids = {entry["id"] for entry in data}
    assert "core" in ids
    assert all(entry["active"] is False for entry in data)


def test_desktop_status_human_output(capsys) -> None:
    exit_code = main(["desktop", "status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN DESKTOP" in captured.out
    assert "Serein preset applied" in captured.out


def test_desktop_doctor_human_output_exits_zero_or_one(capsys) -> None:
    exit_code = main(["desktop", "doctor"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    assert "SEREIN DESKTOP DOCTOR" in captured.out
    assert "Summary:" in captured.out


def test_desktop_doctor_json_is_well_formed(capsys) -> None:
    exit_code = main(["desktop", "doctor", "--json"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert "checks" in data


def test_desktop_plan_human_output(capsys) -> None:
    exit_code = main(["desktop", "plan"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Desktop installation plan" in captured.out
    assert "plasma-desktop" in captured.out


def test_desktop_plan_json_is_well_formed_and_deterministic(capsys) -> None:
    exit_code = main(["desktop", "plan", "--json"])
    first = capsys.readouterr().out
    assert exit_code == 0
    main(["desktop", "plan", "--json"])
    second = capsys.readouterr().out
    assert first == second
    data = json.loads(first)
    assert data["schema_version"] == 1
    assert "packages" in data


def test_desktop_config_status_human_output(capsys) -> None:
    exit_code = main(["desktop", "config", "status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN DESKTOP CONFIG RESOURCES" in captured.out


def test_hardware_status_human_output(capsys) -> None:
    exit_code = main(["hardware", "status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN HARDWARE" in captured.out
    assert "CPU" in captured.out
    assert "Thermal" in captured.out


def test_hardware_status_never_prints_hostname_or_username(capsys, monkeypatch) -> None:
    import getpass
    import socket

    monkeypatch.setenv("USER", "should-not-appear")
    exit_code = main(["hardware", "status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert socket.gethostname() not in captured.out
    assert getpass.getuser() not in captured.out


def test_hardware_doctor_human_output_exits_zero_or_one(capsys) -> None:
    exit_code = main(["hardware", "doctor"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    assert "SEREIN HARDWARE DOCTOR" in captured.out


def test_hardware_doctor_json_is_well_formed(capsys) -> None:
    exit_code = main(["hardware", "doctor", "--json"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    data = json.loads(captured.out)
    assert "checks" in data


def test_hardware_capabilities_human_output(capsys) -> None:
    exit_code = main(["hardware", "capabilities"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN HARDWARE CAPABILITIES" in captured.out
    assert "GPU switching" in captured.out


def test_hardware_capabilities_json_is_well_formed(capsys) -> None:
    exit_code = main(["hardware", "capabilities", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert len(data["capabilities"]) == 10


@pytest.mark.parametrize("profile_id", ["balanced", "dev", "ai", "battery", "cyber"])
def test_hardware_plan_human_output(capsys, profile_id: str) -> None:
    exit_code = main(["hardware", "plan", profile_id])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"SEREIN HARDWARE PLAN - {profile_id}" in captured.out
    assert "Profile available:" in captured.out


@pytest.mark.parametrize("profile_id", ["balanced", "dev", "ai", "battery", "cyber"])
def test_hardware_plan_json_is_well_formed_and_deterministic(capsys, profile_id: str) -> None:
    exit_code = main(["hardware", "plan", profile_id, "--json"])
    first = capsys.readouterr().out
    assert exit_code == 0
    main(["hardware", "plan", profile_id, "--json"])
    second = capsys.readouterr().out
    assert first == second
    data = json.loads(first)
    assert data["schema_version"] == 1
    assert data["profile_id"] == profile_id


def test_hardware_plan_rejects_unknown_profile() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["hardware", "plan", "not-a-real-profile"])
    assert excinfo.value.code != 0


def test_firstboot_status_human_output(capsys) -> None:
    exit_code = main(["firstboot", "status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN FIRSTBOOT" in captured.out
    assert "Eligibility" in captured.out


def test_firstboot_status_json_is_well_formed(capsys) -> None:
    exit_code = main(["firstboot", "status", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert "eligibility_status" in data


def test_firstboot_doctor_human_output_exits_zero_or_one(capsys) -> None:
    exit_code = main(["firstboot", "doctor"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    assert "SEREIN FIRSTBOOT DOCTOR" in captured.out


def test_firstboot_doctor_json_is_well_formed(capsys) -> None:
    exit_code = main(["firstboot", "doctor", "--json"])
    captured = capsys.readouterr()
    assert exit_code in (0, 1)
    data = json.loads(captured.out)
    assert "checks" in data


def test_firstboot_plan_human_output(capsys) -> None:
    exit_code = main(["firstboot", "plan"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SEREIN FIRSTBOOT PLAN" in captured.out
    assert "Mutation: none" in captured.out


def test_firstboot_plan_json_is_well_formed_and_side_effect_free(capsys) -> None:
    exit_code = main(["firstboot", "plan", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert data["mutation"] == "none"
    assert len(data["steps"]) == 11


def test_firstboot_run_is_not_a_main_cli_subcommand() -> None:
    # Section 12: the main interactive CLI only ever exposes read-only
    # firstboot status/doctor/plan - real mutation lives exclusively
    # behind `python -m serein.firstboot run --allow-run`.
    with pytest.raises(SystemExit) as excinfo:
        main(["firstboot", "run"])
    assert excinfo.value.code != 0


def test_no_command_exits_nonzero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["not-a-real-command"])
    assert excinfo.value.code != 0
