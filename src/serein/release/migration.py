"""Versioned migration framework (Phase-7-completion Section 53).

Firstboot runs once for a new installation; future Serein updates
need migrations - firstboot must never be abused for every update.
Each migration is a plain function pair (apply/verify), optionally
reversible, applied in order, never proceeding past a failed step.

No real migration exists yet - nothing has shipped that needs one.
This module is the framework only, proven with synthetic migrations
in ``tests/test_release.py`` (Section 68's own "migration execution,
failed migration" test requirement), matching the same
"architecture proven, no fabricated content" discipline this project
already applies elsewhere (e.g. ``serein.branding.manifest``'s
pending asset requests).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Migration:
    id: str
    from_version: int
    to_version: int
    description: str
    apply: Callable[[Path], None]
    verify: Callable[[Path], bool]
    #: None means not reversible - Section 48: "do not claim universal
    #: rollback if [...] impossible. Classify honestly."
    rollback: Callable[[Path], None] | None = None


@dataclass(frozen=True)
class MigrationResult:
    id: str
    applied: bool
    verified: bool
    rolled_back: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_migrations(
    root: Path, current_version: int, migrations: tuple[Migration, ...]
) -> list[MigrationResult]:
    """Apply every migration whose ``from_version >= current_version``,
    in ascending order, never skipping ahead. Stops at the first
    failure (apply exception or verify returning False) - never
    proceeds past a failed step (Section 53 - "idempotent or
    explicitly checkpointed")."""
    applicable = sorted(
        (m for m in migrations if m.from_version >= current_version),
        key=lambda m: m.from_version,
    )
    results: list[MigrationResult] = []
    for migration in applicable:
        try:
            migration.apply(root)
        except Exception as exc:  # noqa: BLE001 - a migration's own code is untrusted here
            results.append(
                MigrationResult(migration.id, False, False, False, f"apply failed: {exc}")
            )
            break

        verified = False
        try:
            verified = migration.verify(root)
        except Exception as exc:  # noqa: BLE001
            results.append(
                MigrationResult(migration.id, True, False, False, f"verify raised: {exc}")
            )
            break

        if verified:
            results.append(MigrationResult(migration.id, True, True, False, "applied and verified"))
            continue

        rolled_back = False
        if migration.rollback is not None:
            try:
                migration.rollback(root)
                rolled_back = True
            except Exception:  # noqa: BLE001
                rolled_back = False
        results.append(
            MigrationResult(migration.id, True, False, rolled_back, "verification failed")
        )
        break

    return results
