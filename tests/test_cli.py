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


def test_no_command_exits_nonzero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["not-a-real-command"])
    assert excinfo.value.code != 0
