"""Managed-file health checks (Section 39) - the single canonical
detector every other recovery function (status/doctor/plan/repair)
consumes. Never re-derives file classification independently
(Section 2 - "reuse before rewrite" applied within this subsystem
too, exactly the discipline S1-S6.5 already established across
subsystems).

Two classes of managed file:

- **Regeneratable** (`etc/os-release`, `etc/issue`, `etc/issue.net`):
  this system can itself recompute the exact expected content via a
  pure function already shipped in the wheel
  (`serein.branding.os_identity`) - never a separately maintained
  checksum database (Section 36 - no duplicate source of truth).
  `repair` can fix these.
- **Source-staged** (the `owner="system"` desktop resources): their
  expected content lives in the repository tree, which does not exist
  on an installed system (the same `SEREIN-DESKTOP-STAGING-PENDING`
  gap `serein.firstboot.steps.step_desktop_baseline` already
  documents) - only presence can be verified honestly, never content,
  so these are always `UNKNOWN` when present, never falsely `OK`.
  `repair` cannot fix these.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from serein.branding.os_identity import render_issue, render_issue_net, render_os_release
from serein.desktop import config as desktop_config
from serein.hardware._util import DEFAULT_ROOT

from .models import ManagedFileCheck

#: (id, path relative to root, pure content-generator function).
REGENERATABLE_FILES: tuple[tuple[str, str, Callable[[], str]], ...] = (
    ("os-release", "etc/os-release", render_os_release),
    ("issue", "etc/issue", render_issue),
    ("issue-net", "etc/issue.net", render_issue_net),
)


def check_regeneratable_file(
    root: Path, id_: str, relative: str, render: Callable[[], str]
) -> ManagedFileCheck:
    target = root / relative
    if not target.is_file():
        return ManagedFileCheck(id_, str(target), "MISSING", "file does not exist", True)
    try:
        actual = target.read_text(encoding="utf-8")
    except OSError as exc:
        return ManagedFileCheck(id_, str(target), "CORRUPT", f"unreadable: {exc}", True)
    expected = render()
    if actual == expected:
        return ManagedFileCheck(id_, str(target), "OK", "matches expected generated content", True)
    return ManagedFileCheck(
        id_, str(target), "MODIFIED", "content differs from expected generated content", True
    )


def _check_desktop_resource(
    root: Path, resource: desktop_config.ConfigResource
) -> ManagedFileCheck:
    target = root / resource.target_path.lstrip("/")
    if not target.is_file():
        return ManagedFileCheck(resource.id, str(target), "MISSING", "file does not exist", False)
    return ManagedFileCheck(
        resource.id, str(target), "UNKNOWN",
        "content cannot be verified - source staging is not yet wired "
        "(SEREIN-DESKTOP-STAGING-PENDING); presence alone is confirmed",
        False,
    )


def check_managed_files(root: Path = DEFAULT_ROOT) -> list[ManagedFileCheck]:
    checks = [
        check_regeneratable_file(root, id_, relative, render)
        for id_, relative, render in REGENERATABLE_FILES
    ]
    checks.extend(
        _check_desktop_resource(root, resource)
        for resource in desktop_config.RESOURCES
        if resource.owner == "system"
    )
    return checks
