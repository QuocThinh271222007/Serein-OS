"""Build-workspace storage diagnostics and ephemeral-CI space reclamation
(S7.0RM Corrective A).

A real Layer-B run failed at the disk-space preflight on a GitHub-hosted
runner with ~13 GiB free against a fixed 20 GiB requirement, before any
base ISO was even downloaded. Lowering the threshold without reducing
actual peak storage would just move the failure later (or hide a real
problem) - this module exists to (a) measure what the build pipeline
actually uses at each stage, and (b) let the pipeline explicitly reduce
its own peak footprint (delete the base ISO once it is no longer
needed) rather than relying solely on generic runner cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from serein.distribution.pathsafety import PathSafetyError, resolve_within


class StorageError(ValueError):
    """Raised when a storage-reclamation target fails its safety
    check - never silently narrowed to "skip the deletion"."""


def directory_size_bytes(path: Path) -> int:
    """Sum of file sizes under ``path`` (apparent size, not blocks) -
    ``0`` if the path does not exist. Safe to call at any pipeline
    stage; never raises for a missing directory."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


@dataclass(frozen=True)
class DiskUsageReport:
    """Non-sensitive storage facts (Section 14) - no host username or
    absolute path ever appears in this structure or its serialized
    form; every field is a byte count."""

    cache_upstream_bytes: int
    build_work_bytes: int
    dist_bytes: int
    free_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "cache_upstream_bytes": self.cache_upstream_bytes,
            "build_work_bytes": self.build_work_bytes,
            "dist_bytes": self.dist_bytes,
            "free_bytes": self.free_bytes,
        }


def measure_disk_usage(repo_root: Path) -> DiskUsageReport:
    """Snapshot the three build-relevant trees plus current free space
    on the filesystem holding ``repo_root``. Call this at transition
    points (before fetch, after extraction, before/after each ISO
    rebuild) to build a real peak-usage picture - never estimate when
    the real number is one filesystem call away."""
    import shutil as _shutil

    cache_dir = repo_root / "cache" / "upstream"
    work_dir = repo_root / "build" / "work"
    dist_dir = repo_root / "dist"

    free = _shutil.disk_usage(repo_root).free if repo_root.exists() else 0

    return DiskUsageReport(
        cache_upstream_bytes=directory_size_bytes(cache_dir),
        build_work_bytes=directory_size_bytes(work_dir),
        dist_bytes=directory_size_bytes(dist_dir),
        free_bytes=free,
    )


def release_base_iso(base_iso: Path, cache_dir: Path) -> bool:
    """Delete the cached base ISO - **only** ever called from an
    explicit ``ephemeral_storage=True`` build (Section 8), never from a
    normal developer build, which must keep its verified cache.

    Fails closed via the same path-confinement discipline as every
    other deletion in this codebase: ``base_iso`` must resolve inside
    ``cache_dir`` or this raises :class:`StorageError` and deletes
    nothing. Returns ``True`` if a file was actually removed, ``False``
    if it was already absent (not an error - idempotent).
    """
    try:
        relative = base_iso.resolve().relative_to(cache_dir.resolve())
    except ValueError as exc:
        raise StorageError(
            f"refusing to release {base_iso} - it is not inside {cache_dir}"
        ) from exc

    try:
        resolve_within(cache_dir, str(relative))
    except PathSafetyError as exc:
        raise StorageError(str(exc)) from exc

    if not base_iso.is_file():
        return False
    base_iso.unlink()
    return True
