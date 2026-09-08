"""``serein distribution status``: a read-only distribution-build summary.

Never triggers a network fetch or a build (Section 78-79) - only checks
whether the pinned base-image contract loads, whether the base file is
already cached on disk, and whether a previous ISO build's output is
present. Never prints an absolute host path (Section 79) - only
filenames relative to the repository's own ``cache/``/``dist/`` trees.
"""

from __future__ import annotations

from pathlib import Path

from serein.distribution.base import BaseImageError, load_base_image_spec
from serein.distribution.models import RELEASE_CHANNEL, DistributionStatus

_REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = _REPO_ROOT / "cache" / "upstream"
DIST_DIR = _REPO_ROOT / "dist"


def build_distribution_status(repo_root: Path = _REPO_ROOT) -> DistributionStatus:
    cache_dir = repo_root / "cache" / "upstream"
    dist_dir = repo_root / "dist"

    try:
        spec = load_base_image_spec(repo_root / "distribution" / "base-image.json")
    except BaseImageError:
        return DistributionStatus(
            base_release="unknown",
            architecture="unknown",
            edition="unknown",
            release_channel=RELEASE_CHANNEL,
            base_configured=False,
            base_cached=False,
            base_verified=False,
            last_iso_filename=None,
            last_iso_exists=False,
        )

    cached_file = cache_dir / spec.filename
    isos = sorted(dist_dir.glob("serein-*.iso")) if dist_dir.is_dir() else []
    last_iso = isos[-1] if isos else None

    return DistributionStatus(
        base_release=f"{spec.release}{f' ({spec.point_release})' if spec.point_release else ''}",
        architecture=spec.architecture,
        edition=spec.edition,
        release_channel=RELEASE_CHANNEL,
        base_configured=True,
        base_cached=cached_file.is_file(),
        base_verified=spec.verified,
        last_iso_filename=last_iso.name if last_iso else None,
        last_iso_exists=last_iso is not None,
    )
