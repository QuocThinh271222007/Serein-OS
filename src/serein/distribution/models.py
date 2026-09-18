"""Structured representations for the Distribution subsystem (S7.0).

Mirrors the pattern S2-S6.5 established - dataclasses only, no behavior,
no runtime dependency on any ISO/build tool. See docs/distribution/architecture.md.

The governing principle (docs/distribution/architecture.md): the upstream
base ISO is immutable evidence, never mutated in place; a build is a
*controlled, inspectable overlay* on top of it, and "payload embedded on
media" is never conflated with "payload installed into a target OS"
(that distinction is S7.1/S7.2 territory - see docs/distribution/
known-limitations.md).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from serein import __version__ as _SEREIN_VERSION

DISTRIBUTION_BASE_IMAGE_SCHEMA_VERSION = 1
DISTRIBUTION_PAYLOAD_MANIFEST_SCHEMA_VERSION = 1
DISTRIBUTION_BUILD_MANIFEST_SCHEMA_VERSION = 1
DISTRIBUTION_BUILD_SCHEMA = 1

#: Serein's own build-tooling identity, independent of the Python package
#: version (Section 14 of the S7.0 contract) - bump only when the build
#: *pipeline itself* changes in a way that could affect output. Bumped
#: to 0.2 in S7.0R: the canonical pipeline now builds and embeds the
#: Serein wheel, resets the extraction workspace before every build,
#: and can produce a QA boot variant - all material changes to what a
#: build actually produces.
BUILDER_VERSION = "serein-distribution-builder/0.2"

#: Overlay content version (Section 16) - bump only when files under
#: distribution/overlay/ change in a way that affects media content.
OVERLAY_VERSION = "serein-overlay/0.1"

RELEASE_CHANNEL = "alpha"

#: ISO9660 volume identifiers are limited to 32 characters, upper-case
#: letters/digits/underscore is the safe, portable subset (Section 29).
VOLUME_ID = "SEREIN_ALPHA"

#: Canonical media marker path (Section 53) - identifies Serein media
#: without claiming payload was installed anywhere.
MEDIA_MARKER_PATH = "serein/manifest.json"
PAYLOAD_MANIFEST_PATH = "serein/payload-manifest.json"


@dataclass(frozen=True)
class BaseImageSpec:
    """Pinned provenance for the upstream Ubuntu image a build remasters.

    A contract, never a live probe result - ``verified`` only becomes
    ``True`` after an actual sha256 (and, where a signature is present,
    GPG) check has run against the real downloaded file in *this*
    environment. See ``schemas/distribution-base-image.schema.json``.
    """

    distribution: str
    release: str
    point_release: str | None
    codename: str
    architecture: str
    edition: str
    source: str
    filename: str
    sha256: str
    sha256sums_url: str
    signature_url: str
    signing_key_fingerprint: str
    signing_key_source: str
    verified: bool
    download_url: str | None = None
    size_bytes: int | None = None
    verified_at: str | None = None
    notes: str = ""
    schema_version: int = DISTRIBUTION_BASE_IMAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PayloadEntry:
    """One file embedded in the Serein payload, with its content hash."""

    path: str  # payload-relative, POSIX separators, never absolute
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class PayloadManifest:
    """Enumerates exactly which repository-derived files are embedded on
    Serein media - never a full worktree copy. See
    ``docs/distribution/payload.md``."""

    source_commit: str
    generated_from: tuple[str, ...]
    entries: tuple[PayloadEntry, ...]
    schema_version: int = DISTRIBUTION_PAYLOAD_MANIFEST_SCHEMA_VERSION

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def total_bytes(self) -> int:
        return sum(e.size_bytes for e in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "generated_from": list(self.generated_from),
            "entry_count": self.entry_count,
            "total_bytes": self.total_bytes,
            "entries": [asdict(e) for e in self.entries],
        }


@dataclass(frozen=True)
class BootValidation:
    """Boot-smoke evidence recorded into a build manifest, if performed
    (Section 45-49). ``status="not_performed"`` is the honest default -
    never inferred from the build having merely succeeded."""

    status: str = "not_performed"  # "not_performed" | "pass" | "fail"
    method: str | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class BuildOutput:
    filename: str
    sha256: str
    size_bytes: int
    volume_id: str = VOLUME_ID


@dataclass(frozen=True)
class BuildManifest:
    """Recorded alongside every successful build as
    ``<iso>.manifest.json`` (Section 16). Deliberately excludes any
    host-identifying field - see docs/distribution/security.md.

    ``release_channel`` (``RELEASE_CHANNEL``, e.g. ``"alpha"``) is this
    build's own maturity/type label - a build-time constant, never
    user-configurable. This is a DIFFERENT concept from
    ``serein.release.channels`` (Phase-7-completion Section 44's
    stable/beta/dev *update* channel - which package stream an
    already-installed system subscribes to, user-configurable
    post-install) - the shared word "channel" is coincidental, never
    conflated.

    ``serein_version`` (Section 51-52) reuses ``serein.__version__``
    directly - never a second, independently-maintained copy."""

    source_commit: str
    base: BaseImageSpec
    payload_manifest_sha256: str
    output: BuildOutput
    boot_validation: BootValidation = field(default_factory=BootValidation)
    release_channel: str = RELEASE_CHANNEL
    build_schema: int = DISTRIBUTION_BUILD_SCHEMA
    builder_version: str = BUILDER_VERSION
    overlay_version: str = OVERLAY_VERSION
    source_date_epoch: int | None = None
    schema_version: int = DISTRIBUTION_BUILD_MANIFEST_SCHEMA_VERSION
    serein_version: str = _SEREIN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "serein_version": self.serein_version,
            "release_channel": self.release_channel,
            "source_commit": self.source_commit,
            "build_schema": self.build_schema,
            "builder_version": self.builder_version,
            "overlay_version": self.overlay_version,
            "source_date_epoch": self.source_date_epoch,
            "base": {
                "distribution": self.base.distribution,
                "release": self.base.release,
                "architecture": self.base.architecture,
                "edition": self.base.edition,
                "sha256": self.base.sha256,
            },
            "payload_manifest_sha256": self.payload_manifest_sha256,
            "output": asdict(self.output),
            "boot_validation": asdict(self.boot_validation),
        }


@dataclass(frozen=True)
class InspectionFinding:
    check: str
    status: str  # "pass" | "fail" | "skip"
    detail: str


@dataclass(frozen=True)
class InspectionReport:
    """Result of a read-only ISO/tree structural inspection (Section 52).
    Never requires mounting the medium."""

    target: str  # "iso" | "extracted-tree", never an absolute host path
    findings: tuple[InspectionFinding, ...]

    @property
    def passed(self) -> bool:
        return all(f.status != "fail" for f in self.findings)

    @property
    def strict_passed(self) -> bool:
        """S7.0R Corrective E: for Layer-B real-media evidence, a
        ``skip`` (e.g. xorriso unavailable) must never be read as
        equivalent to a real pass - every finding must be exactly
        ``"pass"``. Lenient extracted-tree/fixture inspection should
        keep using :attr:`passed`; real-ISO closure evidence must use
        this instead."""
        return bool(self.findings) and all(f.status == "pass" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "passed": self.passed,
            "findings": [asdict(f) for f in self.findings],
        }


@dataclass(frozen=True)
class DistributionStatus:
    """``serein distribution status`` output - read-only, never triggers
    a network fetch or build (Section 78-79)."""

    base_release: str
    architecture: str
    edition: str
    release_channel: str
    base_configured: bool
    base_cached: bool
    base_verified: bool
    last_iso_filename: str | None
    last_iso_exists: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
