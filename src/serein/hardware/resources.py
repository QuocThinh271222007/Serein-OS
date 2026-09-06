"""Canonical list of the hardware policy resources this repository ships
under ``hardware/`` (repo root — planning data, distinct from this
``src/serein/hardware/`` code package). Mirrors the same pattern as
``serein.desktop.config``: nothing here is installed by S2, and
``missing_resources`` lets ``hardware doctor``/tests catch a shipped file
going missing without touching any host.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class HardwareResource:
    id: str
    repo_path: str
    target_path: str
    description: str


RESOURCES: tuple[HardwareResource, ...] = (
    HardwareResource(
        id="zram-generator-defaults",
        repo_path="hardware/defaults/zram-generator.conf",
        target_path="/etc/systemd/zram-generator.conf.d/90-serein.conf",
        description="Serein's ZRAM sizing/algorithm policy, planning-only in S2.",
    ),
)


def repo_root() -> Path:
    return _REPO_ROOT


def missing_resources(root: Path | None = None) -> list[HardwareResource]:
    base = root if root is not None else _REPO_ROOT
    return [r for r in RESOURCES if not (base / r.repo_path).is_file()]
