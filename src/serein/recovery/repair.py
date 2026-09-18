"""``serein-recovery-repair`` - the ONE mutating entrypoint in this
subsystem (Section 38 - "Mutation must require explicit
acknowledgement"). Deliberately kept out of the main interactive CLI
and out of ``status``/``doctor``/``plan`` (all pure read-only) -
mirrors ``serein.firstboot``/``serein.installer``'s own established
separation between a read-only main-CLI surface and a distinct
mutating entrypoint gated behind an explicit flag.

Only ever repairs a **regeneratable** file (Section 39) - a file whose
exact expected content this system can recompute itself via a pure
function already shipped in the wheel. Never touches a
source-staged/``UNKNOWN`` file (Section 39 - "Do NOT blindly overwrite
intentionally user-owned files... system defaults and user
customization must be distinguished") - there is no safe way to
"repair" a file this system cannot independently prove the correct
content of.
"""

from __future__ import annotations

from pathlib import Path

from serein.firstboot.atomic import atomic_write_text
from serein.hardware._util import DEFAULT_ROOT

from .checks import REGENERATABLE_FILES, check_regeneratable_file
from .models import RepairReport, RepairResult

SCHEMA_VERSION = 1


class RecoveryRepairError(RuntimeError):
    """Raised when repair is invoked without explicit authorization."""


def repair_managed_files(root: Path = DEFAULT_ROOT, *, allow_repair: bool) -> RepairReport:
    if not allow_repair:
        raise RecoveryRepairError(
            "repair_managed_files refuses to run without allow_repair=True "
            "(Section 38 - mutation must require explicit acknowledgement)"
        )

    results: list[RepairResult] = []
    for id_, relative, render in REGENERATABLE_FILES:
        before = check_regeneratable_file(root, id_, relative, render)
        if before.status == "OK":
            results.append(
                RepairResult(id_, before.target_path, False, "already OK, no repair needed")
            )
            continue

        target = root / relative
        atomic_write_text(target, render())

        after = check_regeneratable_file(root, id_, relative, render)
        repaired = after.status == "OK"
        detail = "regenerated and reverified" if repaired else "wrote but reverification failed"
        results.append(RepairResult(id_, before.target_path, repaired, detail))

    return RepairReport(schema_version=SCHEMA_VERSION, results=results)
