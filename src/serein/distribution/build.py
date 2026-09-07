"""The single canonical Serein ISO build entrypoint (S7.0 Section 13;
wheel embedding, clean workspace, and QA variant added by S7.0R;
storage-efficient sequencing added by S7.0RM Corrective A).

``run_build`` is what ``distribution/scripts/build-iso.sh`` and
``python -m serein.distribution build`` both call - there is exactly one
build pipeline, not several competing paths (Section 9 of the S7.0RM
corrective forbids a second "ci-special" build script). It never runs
implicitly (no import of this module triggers a build), never
downloads anything (the base image must already be fetched and
verified - see ``serein.distribution.base``), and fails closed at the
first unverified/unsafe step rather than continuing best-effort.

Pipeline (storage-aware ordering - Section 48 of the S7.0RM corrective):

    verify base checksum
    -> reset extraction workspace (guaranteed empty - Corrective D)
    -> extract base ISO (rootless, read-only source)
    -> capture the base image's own El Torito report (needs base_iso)
    -> [ephemeral_storage only] release the cached base ISO - it is
       never needed again after extraction + the report above
    -> apply static overlay (allowlisted destinations only)
    -> build + content-verify the Serein wheel (Corrective C)
    -> assemble resource payload + wheel artifact, copy into the tree
    -> write dynamic media marker + payload manifest
    -> rebuild CANONICAL production ISO with xorriso (bytes finalized)
    -> record production build manifest + sha256
    -> transition the SAME extraction in place into QA boot form
       (Corrective B/A - no second multi-GB tree copy; every file
       outside the GRUB config + checksum catalog is hash-verified
       unchanged, or the QA step is blocked, never silently unsafe)
    -> rebuild QA ISO reusing the same boot flags
    -> record QA build manifest + sha256 (best-effort - QA_BUILD may be
       BLOCKED without failing the already-finalized production build)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from serein.distribution.base import BaseImageError, load_base_image_spec, verify_base_image
from serein.distribution.iso import (
    build_extract_command,
    build_rebuild_command,
    build_report_command,
    parse_el_torito_report,
)
from serein.distribution.manifest import assemble_build_manifest, write_build_manifest
from serein.distribution.models import (
    MEDIA_MARKER_PATH,
    PAYLOAD_MANIFEST_PATH,
    VOLUME_ID,
    BaseImageSpec,
    BuildManifest,
)
from serein.distribution.overlay import apply_overlay
from serein.distribution.pathsafety import resolve_within
from serein.distribution.payload import build_wheel, inspect_wheel_contents, wheel_artifact
from serein.distribution.qa_boot import (
    QaBootError,
    QaProtectedFileMutationError,
    transition_to_qa_in_place,
)
from serein.distribution.storage import release_base_iso
from serein.distribution.workspace import reset_extracted_workspace

_REPO_ROOT = Path(__file__).resolve().parents[3]


class BuildError(RuntimeError):
    """Raised for any build-pipeline failure - always fail closed, never
    continue to a later stage after one of these."""


@dataclass(frozen=True)
class BuildPaths:
    repo_root: Path
    work_dir: Path
    output_iso: Path

    @property
    def cache_dir(self) -> Path:
        return self.repo_root / "cache" / "upstream"

    @property
    def extracted_dir(self) -> Path:
        return self.work_dir / "extracted"

    @property
    def qa_output_iso(self) -> Path:
        return self.output_iso.with_name(
            self.output_iso.stem + "-qa" + self.output_iso.suffix
        )


@dataclass(frozen=True)
class BuildResult:
    """Both artifacts one canonical build call produces (Section 44 of
    the S7.0R corrective: one Layer-B pipeline, two ISOs)."""

    production: BuildManifest
    qa: BuildManifest | None
    qa_blocked_reason: str | None = None


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _copy_payload_into_tree(
    extracted_dir: Path, repo_root: Path, source_commit: str, base: BaseImageSpec, wheel_path: Path
) -> str:
    """Assemble the resource + wheel payload, copy every artifact's
    real bytes into the extracted tree, and write the two dynamic
    per-build JSON files (Section 53-54). Returns the payload
    manifest's own sha256 for the build manifest."""
    from serein.distribution.models import PayloadManifest
    from serein.distribution.payload import PAYLOAD_RESOURCE_ROOTS, collect_resource_artifacts

    artifacts = collect_resource_artifacts(repo_root)
    artifacts.append(wheel_artifact(wheel_path))

    payload_manifest = PayloadManifest(
        source_commit=source_commit,
        generated_from=PAYLOAD_RESOURCE_ROOTS,
        entries=tuple(sorted((artifact.entry for artifact in artifacts), key=lambda e: e.path)),
    )

    for artifact in artifacts:
        destination = resolve_within(extracted_dir, f"serein/payload/{artifact.entry.path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(artifact.source_path.read_bytes())

    payload_manifest_dict = payload_manifest.to_dict()
    payload_manifest_json = json.dumps(payload_manifest_dict, indent=2, sort_keys=True) + "\n"
    payload_manifest_path = resolve_within(extracted_dir, PAYLOAD_MANIFEST_PATH)
    payload_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload_manifest_path.write_text(payload_manifest_json, encoding="utf-8")

    marker = {
        "distribution": "serein",
        "product": "Serein OS Alpha",
        "source_commit": source_commit,
        "base_release": base.release,
        "base_point_release": base.point_release,
        "architecture": base.architecture,
        "build_schema": 1,
    }
    marker_path = resolve_within(extracted_dir, MEDIA_MARKER_PATH)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return _sha256_hex(payload_manifest_json.encode("utf-8"))


def run_build(
    repo_root: Path = _REPO_ROOT,
    work_dir: Path | None = None,
    output_iso: Path | None = None,
    source_commit: str = "",
    subprocess_runner: object = subprocess.run,
    build_qa_variant: bool = True,
    ephemeral_storage: bool = False,
) -> BuildResult:
    """Run the full build pipeline and return both the production and
    (if not blocked) QA build manifests.

    ``subprocess_runner`` defaults to the real ``subprocess.run`` but
    may be replaced with a fake in tests (Section 89) - it must accept
    the same positional/``check`` signature; it is used for every
    external tool invocation this pipeline makes (extraction, wheel
    build, El Torito report, both ISO rebuilds).

    ``ephemeral_storage=True`` (Section 8-9 of the S7.0RM corrective)
    deletes the cached base ISO from ``cache/upstream/`` immediately
    after it is no longer needed (extraction + the El Torito report
    both already captured) - intended **only** for an ephemeral CI
    runner's Layer-B job, never for a normal developer build, which
    must keep its verified cache. The canonical distribution builder
    stays the single shared pipeline either way (Section 9 - "do not
    create two competing build pipelines"); this is one explicit
    keyword argument, not a parallel script.
    """
    if not source_commit:
        raise BuildError("source_commit is required - a build must record real provenance")

    paths = BuildPaths(
        repo_root=repo_root,
        work_dir=work_dir or (repo_root / "build" / "work"),
        output_iso=output_iso or (repo_root / "dist" / "serein-alpha-26.04-amd64.iso"),
    )

    try:
        spec = load_base_image_spec(repo_root / "distribution" / "base-image.json")
    except BaseImageError as exc:
        raise BuildError(f"base image contract invalid: {exc}") from exc

    base_iso = paths.cache_dir / spec.filename
    try:
        verify_base_image(base_iso, spec)
    except BaseImageError as exc:
        raise BuildError(f"base image verification failed: {exc}") from exc

    paths.work_dir.mkdir(parents=True, exist_ok=True)
    reset_extracted_workspace(paths.work_dir, paths.extracted_dir)
    _run(subprocess_runner, build_extract_command(base_iso, paths.extracted_dir))

    # El Torito report captured right after extraction, while base_iso
    # still exists - this is the last pipeline step that needs it, so
    # ephemeral_storage can release the ~6 GB file immediately after,
    # before the two ISO rebuilds (the phase with the highest disk
    # pressure) ever begin.
    report_result = _run(subprocess_runner, build_report_command(base_iso), capture=True)
    boot_flags = parse_el_torito_report(report_result)

    if ephemeral_storage:
        release_base_iso(base_iso, paths.cache_dir)

    overlay_source = repo_root / "distribution" / "overlay"
    apply_overlay(overlay_source, paths.extracted_dir)

    wheel_path = build_wheel(repo_root, subprocess_runner=subprocess_runner)
    inspect_wheel_contents(wheel_path)

    payload_manifest_sha256 = _copy_payload_into_tree(
        paths.extracted_dir, repo_root, source_commit, spec, wheel_path
    )

    paths.output_iso.parent.mkdir(parents=True, exist_ok=True)
    rebuild_cmd = build_rebuild_command(
        paths.extracted_dir, boot_flags, paths.output_iso, VOLUME_ID
    )
    _run(subprocess_runner, rebuild_cmd)

    production_manifest = assemble_build_manifest(
        source_commit=source_commit,
        base=spec,
        payload_manifest_sha256=payload_manifest_sha256,
        output_iso=paths.output_iso,
        volume_id=VOLUME_ID,
    )
    write_build_manifest(production_manifest, paths.output_iso)

    if not build_qa_variant:
        return BuildResult(production=production_manifest, qa=None)

    # Production ISO bytes are already finalized on disk above - only
    # now may the QA transition begin (Section 6's required invariant).
    try:
        transition_to_qa_in_place(paths.extracted_dir)
    except QaProtectedFileMutationError as exc:
        # A genuine safety violation (something outside the GRUB
        # config/checksum catalog changed) - never silently degrade to
        # "QA blocked, production still fine"; the production ISO is
        # already finalized and unaffected, but this signals the QA
        # transition logic itself is unsafe and must fail loudly.
        raise BuildError(f"QA transition safety check failed: {exc}") from exc
    except QaBootError as exc:
        return BuildResult(production=production_manifest, qa=None, qa_blocked_reason=str(exc))

    qa_rebuild_cmd = build_rebuild_command(
        paths.extracted_dir, boot_flags, paths.qa_output_iso, VOLUME_ID
    )
    _run(subprocess_runner, qa_rebuild_cmd)

    qa_manifest = assemble_build_manifest(
        source_commit=source_commit,
        base=spec,
        payload_manifest_sha256=payload_manifest_sha256,
        output_iso=paths.qa_output_iso,
        volume_id=VOLUME_ID,
    )
    write_build_manifest(qa_manifest, paths.qa_output_iso)

    return BuildResult(production=production_manifest, qa=qa_manifest)


def _run(runner: object, argv: list[str], capture: bool = False) -> str:
    result = runner(argv, capture_output=True, text=True, check=False)  # type: ignore[operator]
    if result.returncode != 0:
        raise BuildError(f"command failed ({' '.join(argv)}): {result.stderr}")
    return result.stdout if capture else ""
