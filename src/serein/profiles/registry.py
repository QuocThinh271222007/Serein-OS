"""Combines on-disk profile manifests with declared-but-unbuilt profile
identities into the list ``serein profile list`` shows.

As of S2, every profile named in the roadmap (``core``, ``desktop``,
``balanced``, ``dev``, ``ai``, ``battery``, ``cyber``) has a real manifest
under ``profiles/<id>/<id>.profile.json`` — ``DECLARED_ONLY_PROFILES`` is
empty for now, kept only as the mechanism a future phase (e.g. S6's veil/
privacy profile) will use before it has a manifest of its own. "implemented"
for ``balanced``/``dev``/``ai``/``battery``/``cyber`` means their hardware
resource-policy layer is real (see ``docs/hardware/architecture.md``) —
their S3/S4/S5 application/tooling layers remain entirely separate,
unimplemented future work; this distinction is documented in
``docs/architecture/profile-contract.md``, not left implicit. Activation
is not implemented yet: every entry reports ``active=False``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from serein.profiles.models import ProfileEntry, ProfileManifest

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILES_DIR = _REPO_ROOT / "profiles"


@dataclass(frozen=True)
class _DeclaredProfile:
    id: str
    name: str
    description: str


# Profile identities named in the roadmap (docs/roadmap.md) that have no
# manifest yet. Empty as of S2 — every roadmap profile now has one. A
# future phase (e.g. S6's veil/privacy profile) adds an entry here before
# it has a manifest of its own.
DECLARED_ONLY_PROFILES: tuple[_DeclaredProfile, ...] = ()


def _load_manifests(profiles_dir: Path) -> dict[str, ProfileManifest]:
    manifests: dict[str, ProfileManifest] = {}
    if not profiles_dir.is_dir():
        return manifests

    for manifest_path in sorted(profiles_dir.glob("*/*.profile.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ProfileManifest.from_dict(data)
        except (OSError, ValueError, KeyError):
            continue
        manifests[manifest.id] = manifest

    return manifests


def list_profiles(profiles_dir: Path = DEFAULT_PROFILES_DIR) -> list[ProfileEntry]:
    manifests = _load_manifests(profiles_dir)
    entries: dict[str, ProfileEntry] = {
        manifest.id: ProfileEntry(
            id=manifest.id,
            name=manifest.name,
            description=manifest.description,
            status=manifest.status,
            active=False,
        )
        for manifest in manifests.values()
    }

    for declared in DECLARED_ONLY_PROFILES:
        if declared.id in entries:
            continue  # a manifest exists; it takes precedence
        entries[declared.id] = ProfileEntry(
            id=declared.id,
            name=declared.name,
            description=declared.description,
            status="declared",
            active=False,
        )

    return sorted(entries.values(), key=lambda entry: entry.id)
