"""Clean, reproducible build-workspace preparation (S7.0R Corrective D).

A prior pass let ``run_build`` do ``extracted_dir.mkdir(exist_ok=True)``
and extract on top of whatever was already there - a stale file from a
previous build (or a previous, now-wrong overlay/payload write) could
silently survive into a new build's output, breaking the "same inputs
-> same logical content" reproducibility contract
(``docs/distribution/iso-build.md``).

``reset_extracted_workspace`` guarantees the extraction target starts
empty, every time, without depending on a developer remembering to run
``clean.sh`` first - and it never risks deleting anything outside the
declared build workspace, reusing the same
:mod:`serein.distribution.pathsafety` primitives ``clean.sh`` itself
relies on.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from serein.distribution.pathsafety import is_safe_cleanup_target


class WorkspaceError(ValueError):
    """Raised when a workspace-reset target fails the safe-delete
    invariant - never silently narrowed to "skip the reset"."""


def reset_extracted_workspace(work_dir: Path, extracted_dir: Path) -> None:
    """Guarantee ``extracted_dir`` exists and is empty, deleting any
    prior content first.

    Two independent checks must both pass before anything is deleted:

    1. ``extracted_dir`` must resolve to exactly ``work_dir/"extracted"``
       - the one canonical extraction target
       (:class:`serein.distribution.build.BuildPaths`), never an
       arbitrary caller-supplied path.
    2. :func:`serein.distribution.pathsafety.is_safe_cleanup_target`
       must confirm the resolved path is genuinely inside
       ``work_dir`` (Section 74's "safe delete invariant") - this also
       transparently rejects a symlinked ``extracted_dir`` that
       resolves outside ``work_dir``, since resolution happens before
       the containment check.

    Never touches ``cache/upstream/`` (the verified base image) or
    ``dist/`` (prior build output) - both live outside ``work_dir``
    entirely and are never passed to this function.
    """
    work_dir_resolved = work_dir.resolve()
    expected = (work_dir_resolved / "extracted")

    # Compare the unresolved expected path's resolution against the
    # caller's target - if extracted_dir is a symlink, its resolution
    # will differ from `expected` and this rejects it before deletion.
    try:
        target_resolved = extracted_dir.resolve()
    except OSError as exc:
        raise WorkspaceError(f"cannot resolve extraction target: {extracted_dir}") from exc

    if target_resolved != expected:
        raise WorkspaceError(
            f"refusing to reset {extracted_dir} - it does not resolve to the "
            f"canonical extraction target {expected}"
        )

    if not is_safe_cleanup_target(extracted_dir, allowed_root=work_dir):
        raise WorkspaceError(
            f"refusing to reset {extracted_dir} - it is not confined inside "
            f"the declared build workspace {work_dir}"
        )

    if target_resolved.exists():
        shutil.rmtree(target_resolved)

    target_resolved.mkdir(parents=True, exist_ok=False)
