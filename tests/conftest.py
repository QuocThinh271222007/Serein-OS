"""Shared pytest fixtures.

Nothing here touches the real host: ``host_root`` resolves a fixture
directory under ``tests/fixtures/hosts/`` that stands in for the
filesystem root, per the injectable-``root`` design in
``docs/architecture/hardware-contract.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hosts"


@pytest.fixture
def host_root():
    def _resolve(scenario: str) -> Path:
        path = FIXTURES_DIR / scenario
        assert path.is_dir(), f"unknown fixture host scenario: {scenario}"
        return path

    return _resolve
