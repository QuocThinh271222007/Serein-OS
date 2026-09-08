"""Stable target-disk identity capture and re-validation (S7.1 Sections
11-12).

Device names such as ``/dev/sdb`` are observations, not stable
installation identities - enumeration order can change between the
planning scan and the execution scan (a USB re-plug, another device
appearing/disappearing, kernel re-numbering). This module is the one
place a :class:`~serein.installer.models.TargetDiskIdentity` fingerprint
is captured from a selected :class:`~serein.installer.models.DiskInfo`,
and the one place a later rescan is matched back against it before any
destructive operation is allowed to proceed (TOCTOU protection -
Section 12).
"""

from __future__ import annotations

from serein.installer.models import DiskInfo, DiskInventory, TargetDiskIdentity, TargetResolution

#: Fields, in the order strength is judged (Section 11 - "prefer stable
#: evidence where available: WWN, serial, ID_PATH, model, size").
_STRONG_IDENTITY_FIELDS = ("wwn", "serial", "id_path")


def capture_target_identity(disk: DiskInfo) -> TargetDiskIdentity:
    """Fingerprint ``disk`` at selection time. Always records
    ``observed_device_path`` too (useful diagnostic evidence), but
    matching later never relies on it alone."""
    return TargetDiskIdentity(
        serial=disk.serial,
        wwn=disk.wwn,
        id_path=disk.id_path,
        model=disk.model,
        size_bytes=disk.size_bytes,
        observed_device_path=disk.device_path,
    )


def identity_strength(identity: TargetDiskIdentity) -> int:
    """How many strong (serial/wwn/id_path) fields are present - used
    to decide whether a match is trustworthy enough to proceed on
    (Section 11: "target identity must be strong enough that a later
    rescan can prove THIS IS STILL THE SAME DISK before destructive
    execution")."""
    return sum(1 for name in _STRONG_IDENTITY_FIELDS if getattr(identity, name))


def identity_matches_disk(identity: TargetDiskIdentity, disk: DiskInfo) -> bool:
    """True only if every STRONG field ``identity`` actually carries a
    value for agrees with ``disk`` - a field ``identity`` never
    recorded is neither a match nor a mismatch (never fabricate
    agreement from absence). At least one strong field must actually
    be compared for this to ever return True; a bare model/size-only
    identity can never "match" here (Section 11's strength requirement
    is enforced at the call site via :func:`identity_strength`, but this
    function additionally refuses to treat an all-absent comparison as
    a match)."""
    compared = False
    for name in _STRONG_IDENTITY_FIELDS:
        expected = getattr(identity, name)
        if expected is None:
            continue
        compared = True
        if getattr(disk, name) != expected:
            return False
    if not compared:
        return False
    if identity.size_bytes is not None and disk.size_bytes is not None:
        if identity.size_bytes != disk.size_bytes:
            return False
    return True


def resolve_target(
    identity: TargetDiskIdentity, inventory: DiskInventory, minimum_strength: int = 1
) -> TargetResolution:
    """Re-match ``identity`` against a freshly re-probed ``inventory``
    (Section 12). Returns exactly one of:

    - ``"resolved"`` - exactly one disk in ``inventory`` matches every
      strong field ``identity`` carries, and identity strength meets
      ``minimum_strength``.
    - ``"not_found"`` - no disk matches (device disappeared, or was
      never strong enough to search for).
    - ``"ambiguous"`` - more than one disk matches (Section 34: two
      disks that coincidentally share every recorded strong field) -
      fails closed rather than guessing.
    - ``"changed"`` - the originally observed device path still exists
      but its own identity now disagrees with the captured fingerprint
      (e.g. same path, different serial after a re-plug) - reported
      distinctly from "not_found" for precise diagnostics (Section 37).

    Never falls back to matching by ``observed_device_path`` alone -
    that is exactly the volatile signal this module exists to not
    trust (Section 12: "do not continue using the old /dev/sdX path").
    """
    if identity_strength(identity) < minimum_strength:
        return TargetResolution(
            status="not_found",
            reason=(
                f"captured identity has strength {identity_strength(identity)} "
                f"(< required {minimum_strength}) - too weak to safely re-match"
            ),
        )

    matches = [disk for disk in inventory.disks if identity_matches_disk(identity, disk)]

    if len(matches) > 1:
        return TargetResolution(
            status="ambiguous",
            reason=(
                f"{len(matches)} disks match the captured target identity - "
                "refusing to select one arbitrarily"
            ),
        )
    if len(matches) == 1:
        return TargetResolution(status="resolved", disk=matches[0])

    # No disk matched by strong identity. Distinguish "changed" (the
    # previously observed path still exists, but under a disagreeing
    # identity) from "not_found" (the path itself is gone too) - both
    # block, but with a precise reason (Section 37).
    same_path = next(
        (d for d in inventory.disks if d.device_path == identity.observed_device_path), None
    )
    if same_path is not None:
        return TargetResolution(
            status="changed",
            reason=(
                f"{identity.observed_device_path} still exists but its identity no "
                "longer matches what was captured at selection time"
            ),
        )
    return TargetResolution(
        status="not_found",
        reason="no disk in the current inventory matches the captured target identity",
    )
