"""Read-only ISO/extracted-tree structural inspector (S7.0 Section 52).

Two inspection targets:

- **An extracted ISO tree** (a directory) - inspected directly by
  walking the filesystem. This is what Layer A tests exercise via
  ``distribution/test-fixtures/``, and what a real build's
  post-remaster-but-pre-rebuild step would run.
- **A real ``.iso`` file** - inspected via ``xorriso -indev <iso> -find``
  if ``xorriso`` is on ``PATH``; never mounts the medium (Section 52
  "no mounting required if avoidable"). If ``xorriso`` is unavailable,
  the inspector reports that check as ``skip`` rather than silently
  passing or crashing.

Every check here is a structural presence/consistency check - it never
claims boot *success*, only that the expected artifacts exist where
convention says they should. See ``docs/distribution/boot-validation.md``
for the separate, real-boot-required checks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from serein.distribution.models import InspectionFinding, InspectionReport

#: Relative paths (POSIX) an extracted Ubuntu Desktop hybrid ISO tree is
#: expected to contain an EFI boot image at, per standard hybrid-ISO
#: layout - checked structurally, never assumed without looking.
_EFI_BOOT_CANDIDATES = ("EFI/boot/bootx64.efi", "efi/boot/bootx64.efi")
_BOOT_CATALOG_CANDIDATES = ("boot.catalog", "isolinux/boot.cat", "boot/grub/i386-pc/eltorito.img")


def inspect_extracted_tree(
    tree_root: Path,
    expected_source_commit: str | None = None,
    expected_base_release: str | None = None,
) -> InspectionReport:
    """Structural inspection of an extracted (or overlaid, pre-rebuild)
    ISO tree. Never requires the real multi-GB ISO to exist."""
    findings: list[InspectionFinding] = []

    findings.append(_check_readable(tree_root))
    if not tree_root.is_dir():
        return InspectionReport(target="extracted-tree", findings=tuple(findings))

    media_marker = tree_root / "serein" / "manifest.json"
    findings.append(
        _check_media_marker(media_marker, expected_source_commit, expected_base_release)
    )

    payload_manifest = tree_root / "serein" / "payload-manifest.json"
    findings.append(_check_payload_manifest(payload_manifest, tree_root))

    findings.append(_check_any_present(tree_root, _EFI_BOOT_CANDIDATES, "EFI boot image"))
    findings.append(_check_any_present(tree_root, _BOOT_CATALOG_CANDIDATES, "boot catalog"))

    return InspectionReport(target="extracted-tree", findings=tuple(findings))


def inspect_iso_file(iso_path: Path) -> InspectionReport:
    """Best-effort structural inspection of a real ``.iso`` file via
    ``xorriso -indev <iso> -find``. Reports ``skip`` (never a silent
    pass) if ``xorriso`` is not installed in this environment."""
    findings: list[InspectionFinding] = []

    if not iso_path.is_file():
        findings.append(InspectionFinding("iso-readable", "fail", f"{iso_path} does not exist"))
        return InspectionReport(target="iso", findings=tuple(findings))
    findings.append(InspectionFinding("iso-readable", "pass", f"{iso_path} exists and is a file"))

    if shutil.which("xorriso") is None:
        findings.append(
            InspectionFinding(
                "xorriso-structure", "skip", "xorriso not installed in this environment"
            )
        )
        return InspectionReport(target="iso", findings=tuple(findings))

    result = subprocess.run(
        ["xorriso", "-indev", str(iso_path), "-find"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        findings.append(
            InspectionFinding("xorriso-structure", "fail", f"xorriso -find failed: {result.stderr}")
        )
        return InspectionReport(target="iso", findings=tuple(findings))

    listing = result.stdout
    findings.append(InspectionFinding("xorriso-structure", "pass", "xorriso -find succeeded"))

    for label, path in (
        ("media marker", "/serein/manifest.json"),
        ("payload manifest", "/serein/payload-manifest.json"),
    ):
        status = "pass" if path in listing else "fail"
        findings.append(InspectionFinding(f"iso-contains:{path}", status, f"{label} at {path}"))

    return InspectionReport(target="iso", findings=tuple(findings))


def _check_readable(tree_root: Path) -> InspectionFinding:
    if tree_root.is_dir():
        return InspectionFinding("tree-readable", "pass", f"{tree_root} is a readable directory")
    return InspectionFinding("tree-readable", "fail", f"{tree_root} is not a directory")


def _check_media_marker(
    marker_path: Path, expected_commit: str | None, expected_release: str | None
) -> InspectionFinding:
    if not marker_path.is_file():
        return InspectionFinding("media-marker", "fail", f"missing {marker_path}")
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return InspectionFinding("media-marker", "fail", f"{marker_path} is not valid JSON")

    required = {"distribution", "source_commit", "base_release", "architecture", "build_schema"}
    missing = required - data.keys()
    if missing:
        return InspectionFinding("media-marker", "fail", f"missing fields: {sorted(missing)}")

    if expected_commit is not None and data.get("source_commit") != expected_commit:
        return InspectionFinding(
            "media-marker", "fail",
            f"source_commit {data.get('source_commit')!r} != expected {expected_commit!r}",
        )
    if expected_release is not None and data.get("base_release") != expected_release:
        return InspectionFinding(
            "media-marker", "fail",
            f"base_release {data.get('base_release')!r} != expected {expected_release!r}",
        )
    return InspectionFinding("media-marker", "pass", f"{marker_path} present and well-formed")


def _check_payload_manifest(manifest_path: Path, tree_root: Path) -> InspectionFinding:
    if not manifest_path.is_file():
        return InspectionFinding("payload-manifest", "fail", f"missing {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return InspectionFinding("payload-manifest", "fail", f"{manifest_path} is not valid JSON")

    entries = data.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return InspectionFinding("payload-manifest", "fail", "payload manifest has no entries")

    import hashlib

    for entry in entries:
        entry_path = tree_root / "serein" / "payload" / entry["path"]
        if not entry_path.is_file():
            return InspectionFinding(
                "payload-manifest", "fail", f"payload entry missing on disk: {entry['path']}"
            )
        digest = hashlib.sha256(entry_path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            return InspectionFinding(
                "payload-manifest", "fail", f"payload entry hash mismatch: {entry['path']}"
            )
    return InspectionFinding(
        "payload-manifest", "pass", f"{len(entries)} payload entries present and hash-verified"
    )


def _check_any_present(
    tree_root: Path, candidates: tuple[str, ...], label: str
) -> InspectionFinding:
    for candidate in candidates:
        if (tree_root / candidate).exists():
            return InspectionFinding(f"boot-structure:{label}", "pass", f"found {candidate}")
    return InspectionFinding(
        f"boot-structure:{label}", "fail", f"none of {candidates} present"
    )
