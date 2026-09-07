"""Path-safety primitives shared by payload assembly, overlay application,
and cleanup (S7.0 Sections 68-69, 73-74).

Three genuinely separate operations reuse the same discipline:

- payload assembly copies allowlisted repository files into a build tree
- overlay application writes allowlisted static files onto an extracted
  ISO tree
- cleanup recursively deletes a build workspace directory

Each must refuse a ``../`` traversal, an absolute destination path outside
its own root, and a symlink that would resolve outside its root. None of
these functions execute a deletion or write themselves for the traversal
check itself - they only decide whether a path is safe; the caller
performs the actual (already-approved) filesystem operation.
"""

from __future__ import annotations

from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when a path would escape its declared root."""


def resolve_within(root: Path, relative: str) -> Path:
    """Resolve ``relative`` against ``root`` and guarantee the result is
    still inside ``root`` after resolving ``..`` segments and symlinks.

    Rejects:
      - absolute paths (``relative`` must always be a relative path)
      - ``..`` segments that climb above ``root``
      - a symlink (anywhere along the resolved path) that points outside
        ``root``

    Never creates, deletes, or writes anything - purely a safety
    predicate the caller must call before any real filesystem mutation.
    """
    candidate = Path(relative)
    if candidate.is_absolute():
        raise PathSafetyError(f"absolute path not allowed: {relative!r}")

    root_resolved = root.resolve()
    # resolve() collapses ".." even for paths that do not yet exist, and
    # also follows symlinks for any prefix that does exist - both checks
    # (traversal and symlink escape) fall out of the same comparison.
    joined = (root_resolved / candidate).resolve()

    try:
        joined.relative_to(root_resolved)
    except ValueError as exc:
        raise PathSafetyError(
            f"path escapes root: {relative!r} resolved outside {root_resolved}"
        ) from exc

    return joined


def is_safe_cleanup_target(path: Path, allowed_root: Path) -> bool:
    """True only if ``path`` is ``allowed_root`` itself or a real
    descendant of it after resolving symlinks (Section 74's "safe delete
    invariant"). Never trusts an unresolved string or an environment
    variable as a deletion target - the caller must pass an already
    resolved ``Path``."""
    allowed_resolved = allowed_root.resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return False

    return resolved == allowed_resolved or allowed_resolved in resolved.parents
