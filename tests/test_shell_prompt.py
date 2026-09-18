"""Tests for the Serein shell prompt (Phase-7-completion Section 18,
``development/shell/serein-prompt.sh``).

Functional tests actually source the real script in a real bash
process and read back ``$PS1`` - never merely a syntax check (Section
29/82's own "do not claim runtime rendering if only syntax was
tested" applied here to a shell script instead of a JSON config).
Skips (never fails) when no POSIX shell is available, matching this
project's own established Windows/CI-portability discipline
(``tests/test_installer.py``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_SCRIPT = REPO_ROOT / "development" / "shell" / "serein-prompt.sh"


def _bash() -> str:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash available to execute the prompt script")
    return bash


def _run_prompt(cwd: Path, setup: str = "") -> str:
    script = (
        f'source "{PROMPT_SCRIPT.as_posix()}"\n'
        f"{setup}\n"
        "serein_prompt\n"
        'printf "%s" "$PS1"\n'
    )
    result = subprocess.run(
        [_bash(), "--norc", "--noprofile", "-c", script],
        cwd=cwd, capture_output=True, text=True, timeout=30, check=False,
    )
    return result.stdout


def _init_repo(repo: Path) -> None:
    env_args = ["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo)]
    subprocess.run(env_args, check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True
    )


class TestSyntax:
    def test_bash_syntax_is_valid(self) -> None:
        result = subprocess.run(
            [_bash(), "-n", str(PROMPT_SCRIPT)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr


class TestOutsideGitRepo:
    def test_no_git_segment_no_asterisk(self, tmp_path: Path) -> None:
        ps1 = _run_prompt(tmp_path)
        assert "*" not in ps1
        assert ps1.rstrip().endswith(">")


class TestInsideCleanRepo:
    def test_shows_branch_name_no_asterisk(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        ps1 = _run_prompt(repo)
        assert "main" in ps1
        assert "*" not in ps1
        assert "!" not in ps1

    def test_double_space_separates_cwd_from_branch(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        ps1 = _run_prompt(repo)
        assert "  main" in ps1


class TestDirtyRepo:
    def test_uncommitted_change_shows_asterisk(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        ps1 = _run_prompt(repo)
        assert "main*" in ps1


class TestErrorExitCode:
    def test_nonzero_exit_shows_bang(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        ps1 = _run_prompt(repo, setup="false")
        assert "main !" in ps1

    def test_zero_exit_shows_no_bang(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        ps1 = _run_prompt(repo, setup="true")
        assert "!" not in ps1
