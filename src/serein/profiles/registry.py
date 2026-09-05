"""Combines on-disk profile manifests with declared-but-unbuilt profile
identities into the list ``serein profile list`` shows.

Only ``core`` has a manifest in S0 (``profiles/core/core.profile.json``).
The remaining identities from the roadmap (desktop, dev, ai, battery,
cyber) are named here so the contract is visible, but carry no manifest,
no packages, and no behavior — listing them is not a promise they work.
Activation is not implemented in S0: every entry reports ``active=False``.
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


# Profile identities named in the S0 roadmap (docs/roadmap.md) that have no
# manifest yet. Keep in id order matching the roadmap phase they belong to.
DECLARED_ONLY_PROFILES: tuple[_DeclaredProfile, ...] = (
    _DeclaredProfile(
        "balanced",
        "Balanced",
        "Default day-to-day workstation profile. Declared for S2 (Hardware).",
    ),
    _DeclaredProfile(
        "dev",
        "Development",
        "Software development toolchain profile. Declared for S3 (Development).",
    ),
    _DeclaredProfile(
        "ai",
        "AI Workstation",
        "Local AI/ML workload profile. Declared for S4 (AI).",
    ),
    _DeclaredProfile(
        "battery",
        "Battery Saver",
        "Power-constrained laptop profile. Declared for S2 (Hardware).",
    ),
    _DeclaredProfile(
        "cyber",
        "Cybersecurity Research",
        "Isolated security research/testing profile. Declared for S5 (Cybersecurity).",
    ),
)


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
