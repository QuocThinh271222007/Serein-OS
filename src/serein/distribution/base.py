"""Upstream base-image contract: loading ``distribution/base-image.json``
and verifying a downloaded file's checksum against it (S7.0 Sections 9-11).

This module never downloads anything itself - see
``distribution/scripts/fetch-base-image.sh`` for the only place a
multi-GB network fetch happens, and Section 12 ("no silent network
downloads") for why that must stay a separate, deliberate operation.

Required conceptual flow (Section 10):

    download -> sha256 verify -> only then extract

A build must fail closed if the checksum does not match; this module's
job is to make that check trivial to call and impossible to skip.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from serein.distribution.models import BaseImageSpec

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_IMAGE_JSON = _REPO_ROOT / "distribution" / "base-image.json"

#: 64 KiB read chunks keep memory flat regardless of ISO size.
_HASH_CHUNK_SIZE = 64 * 1024


class BaseImageError(ValueError):
    """Raised for a malformed base-image contract or a checksum
    mismatch. Callers must treat this as fail-closed - never proceed to
    extraction after catching it."""


def load_base_image_spec(path: Path = DEFAULT_BASE_IMAGE_JSON) -> BaseImageSpec:
    """Load and structurally validate ``distribution/base-image.json``.

    Does not touch the network and does not require the actual ISO file
    to exist - this only parses the pinned contract."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BaseImageError(f"base image contract not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BaseImageError(f"base image contract is not valid JSON: {path}") from exc

    required = {
        "distribution", "release", "point_release", "codename", "architecture",
        "edition", "source", "filename", "sha256", "sha256sums_url",
        "signature_url", "signing_key_fingerprint", "signing_key_source", "verified",
    }
    missing = required - raw.keys()
    if missing:
        raise BaseImageError(f"base image contract missing fields: {sorted(missing)}")

    if raw["distribution"] != "ubuntu":
        raise BaseImageError(f"unsupported distribution: {raw['distribution']!r}")
    if raw["architecture"] != "amd64":
        raise BaseImageError(f"unsupported architecture: {raw['architecture']!r}")
    if raw["edition"] not in ("desktop", "server"):
        raise BaseImageError(f"unsupported edition: {raw['edition']!r}")

    sha256 = raw["sha256"]
    if not (isinstance(sha256, str) and len(sha256) == 64 and _is_hex(sha256)):
        raise BaseImageError(f"sha256 is missing or malformed: {sha256!r}")

    return BaseImageSpec(
        distribution=raw["distribution"],
        release=raw["release"],
        point_release=raw["point_release"],
        codename=raw["codename"],
        architecture=raw["architecture"],
        edition=raw["edition"],
        source=raw["source"],
        filename=raw["filename"],
        sha256=sha256,
        sha256sums_url=raw["sha256sums_url"],
        signature_url=raw["signature_url"],
        signing_key_fingerprint=raw["signing_key_fingerprint"],
        signing_key_source=raw["signing_key_source"],
        verified=bool(raw["verified"]),
        download_url=raw.get("download_url"),
        size_bytes=raw.get("size_bytes"),
        verified_at=raw.get("verified_at"),
        notes=raw.get("notes", ""),
    )


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def sha256_file(path: Path) -> str:
    """Stream-hash ``path``. Never loads the whole file into memory -
    safe for a multi-GB ISO."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_base_image(path: Path, spec: BaseImageSpec) -> None:
    """Fail closed: raise ``BaseImageError`` unless ``path`` exists and
    its sha256 matches ``spec.sha256`` exactly. Never partially trusts a
    file (e.g. by size alone)."""
    if not path.is_file():
        raise BaseImageError(f"base image not present at {path} - run fetch-base-image.sh first")

    actual = sha256_file(path)
    if actual != spec.sha256:
        raise BaseImageError(
            f"checksum mismatch for {path.name}: expected {spec.sha256}, got {actual} - "
            "refusing to build from an unverified base image"
        )
