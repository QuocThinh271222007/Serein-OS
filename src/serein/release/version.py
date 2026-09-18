"""Serein release version model (Phase-7-completion Section 51-52).

One canonical mapping - never a Git SHA in one place, a package
version elsewhere, an os-release field elsewhere, and a Fastfetch
field elsewhere all independently maintained (Section 36 - no
duplicate source of truth). Every field here is sourced from an
existing single source of truth, never re-declared:

- ``serein_version`` - ``serein.__version__`` (already the "single
  authoritative source of the control-plane version" per that
  module's own docstring; ``pyproject.toml`` already reads it
  dynamically rather than duplicating it).
- ``source_commit`` - the exact same value
  ``serein.installer.payload.InstallStateMarker.source_commit`` /
  ``serein.distribution.models.BuildManifest.source_commit`` already
  carry for an installed system / a built ISO respectively - this
  module never re-derives it independently.
- ``channel`` - ``serein.release.channels``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from serein import __version__ as SEREIN_VERSION
from serein.release.channels import DEFAULT_CHANNEL

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReleaseVersion:
    schema_version: int
    serein_version: str
    channel: str
    source_commit: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_release_version(
    source_commit: str | None = None, channel: str = DEFAULT_CHANNEL
) -> ReleaseVersion:
    return ReleaseVersion(
        schema_version=SCHEMA_VERSION,
        serein_version=SEREIN_VERSION,
        channel=channel,
        source_commit=source_commit,
    )
