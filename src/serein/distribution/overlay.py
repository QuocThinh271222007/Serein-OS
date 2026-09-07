"""Overlay application onto an extracted ISO tree (S7.0 Sections 22, 69-71).

Only a small, explicit allowlist of destination roots may ever be
written by the overlay step - never an arbitrary recursive copy of
``distribution/overlay/`` onto the extracted tree. Every destination path
is validated with :mod:`serein.distribution.pathsafety` before any write,
so a malformed or malicious overlay source tree cannot escape the
extracted-ISO root.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from serein.distribution.pathsafety import PathSafetyError, resolve_within

#: Destination roots (relative to the extracted ISO tree) the overlay is
#: allowed to write into (Section 69). Anything else is rejected before
#: any write happens.
OVERLAY_ALLOWLIST: tuple[str, ...] = (
    ".disk",
    "serein",
)


class OverlayError(ValueError):
    """Raised when an overlay source file would write outside the
    destination allowlist, or outside the extracted-ISO root entirely."""


@dataclass(frozen=True)
class OverlayPlanEntry:
    source: Path
    destination_relative: str


def plan_overlay(
    overlay_source: Path,
    allowlist: Iterable[str] = OVERLAY_ALLOWLIST,
) -> list[OverlayPlanEntry]:
    """Compute what would be written, without touching the destination
    tree. Every source file must land under one of ``allowlist``'s
    roots; anything else raises :class:`OverlayError` immediately -
    fail closed, never "skip and continue"."""
    entries: list[OverlayPlanEntry] = []
    if not overlay_source.is_dir():
        return entries

    for path in sorted(overlay_source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(overlay_source).as_posix()
        top = relative.split("/", 1)[0]
        if top not in allowlist:
            raise OverlayError(
                f"overlay source {relative!r} is outside the allowlisted "
                f"destination roots {tuple(allowlist)!r}"
            )
        entries.append(OverlayPlanEntry(source=path, destination_relative=relative))
    return entries


def apply_overlay(
    overlay_source: Path,
    extracted_root: Path,
    allowlist: Iterable[str] = OVERLAY_ALLOWLIST,
) -> list[str]:
    """Copy every planned overlay file onto ``extracted_root``.

    Every destination is re-validated with
    :func:`serein.distribution.pathsafety.resolve_within` immediately
    before the write - the allowlist check in :func:`plan_overlay`
    catches an out-of-scope destination *root*, this catches a
    ``../`` or symlink escape *within* an allowed root. Returns the list
    of destination-relative paths actually written.
    """
    written: list[str] = []
    for entry in plan_overlay(overlay_source, allowlist):
        try:
            destination = resolve_within(extracted_root, entry.destination_relative)
        except PathSafetyError as exc:
            raise OverlayError(str(exc)) from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source, destination)
        written.append(entry.destination_relative)
    return written
