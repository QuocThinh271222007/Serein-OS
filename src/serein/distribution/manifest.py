"""Build-manifest assembly and on-disk recording (S7.0 Section 16).

``dist/<iso>.manifest.json`` and ``dist/<iso>.sha256`` are the two files
every successful build must produce alongside the ISO itself. Nothing
here ever writes a username, absolute home path, or hostname into the
manifest - see ``docs/distribution/security.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from serein.distribution.base import sha256_file
from serein.distribution.models import (
    BaseImageSpec,
    BootValidation,
    BuildManifest,
    BuildOutput,
)


def assemble_build_manifest(
    source_commit: str,
    base: BaseImageSpec,
    payload_manifest_sha256: str,
    output_iso: Path,
    volume_id: str,
    boot_validation: BootValidation | None = None,
    source_date_epoch: int | None = None,
) -> BuildManifest:
    """Build a :class:`BuildManifest` from a completed build's real
    output file - the output sha256 is always computed from the actual
    bytes on disk, never assumed."""
    output = BuildOutput(
        filename=output_iso.name,
        sha256=sha256_file(output_iso),
        size_bytes=output_iso.stat().st_size,
        volume_id=volume_id,
    )
    return BuildManifest(
        source_commit=source_commit,
        base=base,
        payload_manifest_sha256=payload_manifest_sha256,
        output=output,
        boot_validation=boot_validation or BootValidation(),
        source_date_epoch=source_date_epoch,
    )


def write_build_manifest(manifest: BuildManifest, output_iso: Path) -> tuple[Path, Path]:
    """Write ``<iso>.manifest.json`` and ``<iso>.sha256`` next to
    ``output_iso``. Returns the two paths written."""
    manifest_path = output_iso.with_suffix(output_iso.suffix + ".manifest.json")
    sha256_path = output_iso.with_suffix(output_iso.suffix + ".sha256")

    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sha256_path.write_text(f"{manifest.output.sha256}  {output_iso.name}\n", encoding="utf-8")
    return manifest_path, sha256_path
