"""Canonical list of the development config resources this repository
ships under ``development/`` (repo root — planning/template data, distinct
from this ``src/serein/development/`` code package).

Mirrors ``serein.desktop.config``/``serein.hardware.resources``'s
pattern. Every resource here is a *template* Serein never writes
automatically: the Zed settings template would only ever be offered as
a starting point (Zed itself decides whether/when to apply user
settings — Serein never overwrites ``~/.config/zed/settings.json``), and
the Git config template is explicitly opt-in documentation, never
written to ``~/.gitconfig``. See docs/development/configuration-ownership.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DevelopmentResource:
    id: str
    repo_path: str
    target_path: str
    owner: str  # "first-login-user" | "user-opt-in"
    description: str


RESOURCES: tuple[DevelopmentResource, ...] = (
    DevelopmentResource(
        id="zed-settings-template",
        repo_path="development/zed/settings.json",
        target_path="~/.config/zed/settings.json",
        owner="first-login-user",
        description=(
            "Recommended Zed settings (dark theme, format-on-save). Never installed "
            "or overwritten automatically - Zed's own first-run behavior, and only "
            "if no existing user settings file is present, per docs/development/"
            "configuration-ownership.md."
        ),
    ),
    DevelopmentResource(
        id="git-recommended-config",
        repo_path="development/git/recommended.gitconfig",
        target_path="(user opt-in only - never written to ~/.gitconfig)",
        owner="user-opt-in",
        description=(
            "Recommended non-identity Git defaults (init.defaultBranch, pull.rebase, "
            "rerere.enabled). Never applied by Serein; documented for the user to "
            "adopt manually if they choose."
        ),
    ),
)


def repo_root() -> Path:
    return _REPO_ROOT


def missing_resources(root: Path | None = None) -> list[DevelopmentResource]:
    base = root if root is not None else _REPO_ROOT
    return [r for r in RESOURCES if not (base / r.repo_path).is_file()]
