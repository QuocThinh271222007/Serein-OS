"""Read-only ISO/extracted-tree structural inspector (S7.0 Section 52;
strict real-ISO evidence added by S7.0R Corrective E).

Three inspection surfaces:

- **An extracted ISO tree** (a directory) - inspected directly by
  walking the filesystem via :func:`inspect_extracted_tree`. This is
  what Layer A tests exercise via ``distribution/test-fixtures/``, and
  what a real build's post-remaster-but-pre-rebuild step would run.
  Uses the lenient :attr:`~serein.distribution.models.InspectionReport.passed`
  semantics (a ``skip`` does not fail it) - appropriate for a
  structural sanity check, not for closure evidence.
- **A real ``.iso`` file, best-effort** - :func:`inspect_iso_file` via
  ``xorriso -indev <iso> -find``; reports ``skip`` (never a silent
  pass) if ``xorriso`` is unavailable. Kept for quick manual checks.
- **A real ``.iso`` file, strict** - :func:`inspect_iso_file_strict`,
  the Layer-B closure inspector. Every check must resolve to exactly
  ``"pass"`` for
  :attr:`~serein.distribution.models.InspectionReport.strict_passed`
  to be true - a ``skip`` (xorriso unavailable) or a ``fail`` both mean
  closure is not proven (Section 36). It extracts ``/serein`` from the
  real ISO bytes (never mounts the medium) and hashes payload entries
  from *those* extracted bytes, never from the source repository
  (Section 39) - this is the one honest way to prove the media that
  will actually ship contains what its own manifest claims.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from serein.distribution.base import sha256_file
from serein.distribution.iso import build_report_command, parse_el_torito_report
from serein.distribution.models import VOLUME_ID, InspectionFinding, InspectionReport
from serein.distribution.pathsafety import resolve_within

#: Relative paths (POSIX) an extracted Ubuntu Desktop hybrid ISO tree is
#: expected to contain an EFI boot image at, per standard hybrid-ISO
#: layout - checked structurally, never assumed without looking.
_EFI_BOOT_CANDIDATES = ("EFI/boot/bootx64.efi", "efi/boot/bootx64.efi")
_BOOT_CATALOG_CANDIDATES = ("boot.catalog", "isolinux/boot.cat", "boot/grub/i386-pc/eltorito.img")

#: Substrings that, if present in a real ``-report_el_torito
#: as_mkisofs`` dump, indicate the base image uses the modern
#: GPT-appended-EFI-System-Partition hybrid layout current Ubuntu
#: Desktop/Server images ship (Section 37 - "do not reduce UEFI
#: validation to only /EFI/boot/bootx64.efi exists"). This is a
#: best-effort heuristic over xorriso's own report text, not a
#: guessed/hardcoded flag set - it has not been validated against a
#: real Ubuntu 26.04.1 xorriso report in this environment (no xorriso
#: installed here); see docs/distribution/known-limitations.md.
_UEFI_EVIDENCE_MARKERS = ("appended_part_as_gpt", "--interval:appended_partition")


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


def inspect_iso_file_strict(
    iso_path: Path,
    work_dir: Path,
    expected_source_commit: str,
    expected_base_release: str = "26.04",
    expected_base_point_release: str | None = "26.04.1",
    expected_architecture: str = "amd64",
    expected_volume_id: str = VOLUME_ID,
    require_wheel: bool = True,
    sidecar_sha256_path: Path | None = None,
    sidecar_manifest_path: Path | None = None,
    runner: object = subprocess.run,
) -> InspectionReport:
    """Strict, Layer-B closure inspection of a real built ``.iso``
    (S7.0R Corrective E).

    Every finding must be exactly ``"pass"`` for
    :attr:`~serein.distribution.models.InspectionReport.strict_passed`
    to be true - unlike :func:`inspect_iso_file`, an unavailable
    ``xorriso`` here produces ``skip`` findings that still fail the
    strict gate (Section 36), never a silent pass. ``runner`` is
    injectable so this whole pipeline is unit-testable with a fake
    ``xorriso`` without the real tool installed - see
    ``tests/test_distribution.py::TestStrictInspector``.

    ``work_dir`` is a scratch directory this function extracts
    ``/serein`` from the real ISO into (via ``xorriso -osirrox on``,
    never a mount) - payload hashes are computed from *those* extracted
    bytes, never from the source repository (Section 39).
    """
    findings: list[InspectionFinding] = []

    if not iso_path.is_file():
        findings.append(InspectionFinding("iso-readable", "fail", f"{iso_path} does not exist"))
        return InspectionReport(target="iso-strict", findings=tuple(findings))
    findings.append(InspectionFinding("iso-readable", "pass", f"{iso_path.name} exists"))

    actual_iso_sha256 = sha256_file(iso_path)
    findings.append(
        InspectionFinding("iso-sha256-computed", "pass", f"sha256={actual_iso_sha256}")
    )

    findings.append(
        _check_sidecar_sha256(iso_path, actual_iso_sha256, sidecar_sha256_path)
    )
    findings.append(
        _check_sidecar_manifest(
            iso_path, actual_iso_sha256, expected_source_commit, sidecar_manifest_path
        )
    )

    if shutil.which("xorriso") is None:
        for check in (
            "xorriso-available", "volume-id", "el-torito-report", "uefi-boot-evidence",
            "extract-serein-tree", "media-marker", "payload-manifest",
        ):
            findings.append(
                InspectionFinding(check, "skip", "xorriso not installed in this environment")
            )
        return InspectionReport(target="iso-strict", findings=tuple(findings))
    findings.append(InspectionFinding("xorriso-available", "pass", "xorriso found on PATH"))

    findings.append(_check_volume_id(iso_path, expected_volume_id, runner))
    el_torito_finding, el_torito_text = _run_el_torito_report(iso_path, runner)
    findings.append(el_torito_finding)
    findings.append(_check_uefi_evidence(el_torito_text))

    extract_root = resolve_within(work_dir, "iso-strict-extract")
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)

    extract_result = runner(  # type: ignore[operator]
        ["xorriso", "-osirrox", "on", "-indev", str(iso_path), "-extract", "/serein",
         str(extract_root / "serein")],
        capture_output=True, text=True, check=False,
    )
    if extract_result.returncode != 0:
        findings.append(
            InspectionFinding(
                "extract-serein-tree", "fail",
                f"xorriso -osirrox extraction failed: {extract_result.stderr}",
            )
        )
        return InspectionReport(target="iso-strict", findings=tuple(findings))
    findings.append(InspectionFinding("extract-serein-tree", "pass", "/serein extracted from ISO"))

    findings.append(
        _check_media_marker(
            extract_root / "serein" / "manifest.json",
            expected_source_commit, expected_base_release,
            expected_base_point_release, expected_architecture,
        )
    )
    findings.append(
        _check_payload_manifest(
            extract_root / "serein" / "payload-manifest.json",
            extract_root, expected_source_commit, require_wheel,
        )
    )

    return InspectionReport(target="iso-strict", findings=tuple(findings))


def _check_sidecar_sha256(
    iso_path: Path, actual_sha256: str, sidecar_path: Path | None
) -> InspectionFinding:
    path = sidecar_path or iso_path.with_suffix(iso_path.suffix + ".sha256")
    if not path.is_file():
        return InspectionFinding("sidecar-sha256", "skip", f"no sidecar at {path.name}")
    first_token = path.read_text(encoding="utf-8").split()[:1]
    if not first_token or first_token[0] != actual_sha256:
        return InspectionFinding(
            "sidecar-sha256", "fail",
            f"sidecar {path.name} sha256 does not match actual ISO bytes ({actual_sha256})",
        )
    return InspectionFinding("sidecar-sha256", "pass", f"{path.name} matches actual ISO bytes")


def _check_sidecar_manifest(
    iso_path: Path, actual_sha256: str, expected_source_commit: str, sidecar_path: Path | None
) -> InspectionFinding:
    path = sidecar_path or iso_path.with_suffix(iso_path.suffix + ".manifest.json")
    if not path.is_file():
        return InspectionFinding("sidecar-manifest", "skip", f"no sidecar at {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return InspectionFinding("sidecar-manifest", "fail", f"{path.name} is not valid JSON")

    output_sha = data.get("output", {}).get("sha256")
    if output_sha != actual_sha256:
        return InspectionFinding(
            "sidecar-manifest", "fail",
            f"{path.name} output.sha256 {output_sha!r} != actual ISO bytes ({actual_sha256})",
        )
    if data.get("source_commit") != expected_source_commit:
        return InspectionFinding(
            "sidecar-manifest", "fail",
            f"{path.name} source_commit {data.get('source_commit')!r} != "
            f"expected {expected_source_commit!r}",
        )
    return InspectionFinding("sidecar-manifest", "pass", f"{path.name} matches actual ISO/source")


def _check_volume_id(iso_path: Path, expected_volume_id: str, runner: object) -> InspectionFinding:
    result = runner(  # type: ignore[operator]
        ["xorriso", "-indev", str(iso_path), "-pvd_info"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return InspectionFinding("volume-id", "fail", f"xorriso -pvd_info failed: {result.stderr}")

    for line in result.stdout.splitlines():
        if "volume id" in line.lower():
            if expected_volume_id in line:
                return InspectionFinding(
                    "volume-id", "pass", f"volume id line contains {expected_volume_id!r}"
                )
            return InspectionFinding(
                "volume-id", "fail",
                f"volume id line does not contain {expected_volume_id!r}: {line!r}",
            )
    return InspectionFinding("volume-id", "fail", "no 'Volume id' line found in -pvd_info output")


def _run_el_torito_report(iso_path: Path, runner: object) -> tuple[InspectionFinding, str]:
    result = runner(build_report_command(iso_path), capture_output=True, text=True, check=False)  # type: ignore[operator]
    if result.returncode != 0:
        return (
            InspectionFinding(
                "el-torito-report", "fail", f"-report_el_torito failed: {result.stderr}"
            ),
            "",
        )
    try:
        flags = parse_el_torito_report(result.stdout)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a real closure blocker
        finding = InspectionFinding("el-torito-report", "fail", f"unparseable report: {exc}")
        return finding, result.stdout
    return (
        InspectionFinding("el-torito-report", "pass", f"{len(flags)} boot flags derived"),
        result.stdout,
    )


def _check_uefi_evidence(el_torito_report_text: str) -> InspectionFinding:
    if not el_torito_report_text:
        return InspectionFinding("uefi-boot-evidence", "fail", "no el-torito report text available")
    for marker in _UEFI_EVIDENCE_MARKERS:
        if marker in el_torito_report_text:
            return InspectionFinding("uefi-boot-evidence", "pass", f"found marker {marker!r}")
    return InspectionFinding(
        "uefi-boot-evidence", "fail",
        f"none of {_UEFI_EVIDENCE_MARKERS} found in el-torito report",
    )


def _check_readable(tree_root: Path) -> InspectionFinding:
    if tree_root.is_dir():
        return InspectionFinding("tree-readable", "pass", f"{tree_root} is a readable directory")
    return InspectionFinding("tree-readable", "fail", f"{tree_root} is not a directory")


def _check_media_marker(
    marker_path: Path,
    expected_commit: str | None,
    expected_release: str | None,
    expected_point_release: str | None = None,
    expected_architecture: str | None = None,
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
    marker_point_release = data.get("base_point_release")
    if expected_point_release is not None and marker_point_release != expected_point_release:
        return InspectionFinding(
            "media-marker", "fail",
            f"base_point_release {data.get('base_point_release')!r} != "
            f"expected {expected_point_release!r}",
        )
    if expected_architecture is not None and data.get("architecture") != expected_architecture:
        return InspectionFinding(
            "media-marker", "fail",
            f"architecture {data.get('architecture')!r} != expected {expected_architecture!r}",
        )
    return InspectionFinding("media-marker", "pass", f"{marker_path} present and well-formed")


def _check_payload_manifest(
    manifest_path: Path,
    tree_root: Path,
    expected_source_commit: str | None = None,
    require_wheel: bool = False,
) -> InspectionFinding:
    if not manifest_path.is_file():
        return InspectionFinding("payload-manifest", "fail", f"missing {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return InspectionFinding("payload-manifest", "fail", f"{manifest_path} is not valid JSON")

    if expected_source_commit is not None and data.get("source_commit") != expected_source_commit:
        return InspectionFinding(
            "payload-manifest", "fail",
            f"payload source_commit {data.get('source_commit')!r} != "
            f"expected {expected_source_commit!r}",
        )

    entries = data.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return InspectionFinding("payload-manifest", "fail", "payload manifest has no entries")

    import hashlib

    saw_wheel = False
    for entry in entries:
        try:
            entry_path_value = entry["path"]
            expected_sha = entry["sha256"]
        except (KeyError, TypeError):
            return InspectionFinding(
                "payload-manifest", "fail", f"malformed payload entry: {entry!r}"
            )
        if entry_path_value.startswith("packages/") and entry_path_value.endswith(".whl"):
            saw_wheel = True

        entry_path = tree_root / "serein" / "payload" / entry_path_value
        if not entry_path.is_file():
            return InspectionFinding(
                "payload-manifest", "fail", f"payload entry missing on disk: {entry_path_value}"
            )
        digest = hashlib.sha256(entry_path.read_bytes()).hexdigest()
        if digest != expected_sha:
            return InspectionFinding(
                "payload-manifest", "fail", f"payload entry hash mismatch: {entry_path_value}"
            )

    if require_wheel and not saw_wheel:
        return InspectionFinding(
            "payload-manifest", "fail", "no packages/*.whl entry present in payload manifest"
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
