"""The Serein profile model: declarative capability manifests.

S0 defines the schema and lists identities; it does not implement
activation/switching. See ``docs/architecture/profile-contract.md``.
"""

from serein.profiles.models import ProfileEntry, ProfileManifest
from serein.profiles.registry import list_profiles

__all__ = ["ProfileEntry", "ProfileManifest", "list_profiles"]
