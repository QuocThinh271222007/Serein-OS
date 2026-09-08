"""Prepare a QA-autoinstall Serein ISO variant for S7.1 Layer-B
installer validation (Section 3, 25).

Takes the ALREADY-BUILT S7.0 QA ISO (``serein-alpha-*-qa.iso``,
produced by ``python -m serein.distribution build``) and extracts it
fresh into a NEW, installer-owned scratch tree - never touching
``distribution``'s own ``build/work/extracted`` (S7.1 owns its own
artifacts; "prefer configuration and adapters, never reopening S7.0
internals" - Section 3-4). Writes a rendered ``autoinstall.yaml`` at
the extracted tree's root - the conventional location Subiquity
auto-detects on the install medium (see
``docs/distribution/upstream-installer-research.md``) - then rebuilds
into ``serein-alpha-*-qa-install.iso`` reusing the SAME real boot flags
the original QA ISO's own El Torito report describes, so this variant
boots identically except for the added autoinstall config.

Reuses ``serein.distribution.iso``'s pure command builders (never
imports or calls anything from ``serein.distribution.build`` - this
module has its own, independent, narrowly-scoped pipeline).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from serein.distribution.iso import (
    build_extract_command,
    build_rebuild_command,
    build_report_command,
    parse_el_torito_report,
)
from serein.distribution.models import VOLUME_ID


class IsoPrepError(RuntimeError):
    """Raised for any QA-install-ISO preparation failure - fail closed,
    never ship a half-prepared variant."""


def prepare_qa_install_iso(
    qa_iso_path: Path,
    work_dir: Path,
    output_iso: Path,
    autoinstall_yaml_text: str,
    subprocess_runner: object = subprocess.run,
) -> Path:
    """Extract ``qa_iso_path``, write ``autoinstall_yaml_text`` at the
    tree root, and rebuild into ``output_iso``. ``subprocess_runner`` is
    injectable (must accept the same positional/``check`` signature as
    ``subprocess.run``) so this whole pipeline is unit-testable with a
    fake ``xorriso`` - mirroring
    ``serein.distribution.build.run_build``'s own injection pattern."""
    if not qa_iso_path.is_file():
        raise IsoPrepError(f"{qa_iso_path} does not exist")

    extracted_dir = work_dir / "qa-install-extracted"
    if extracted_dir.exists():
        shutil.rmtree(extracted_dir)
    extracted_dir.mkdir(parents=True)

    extract_result = subprocess_runner(  # type: ignore[operator]
        build_extract_command(qa_iso_path, extracted_dir),
        capture_output=True, text=True, check=False,
    )
    if extract_result.returncode != 0:
        raise IsoPrepError(f"extraction of {qa_iso_path} failed: {extract_result.stderr}")

    report_result = subprocess_runner(  # type: ignore[operator]
        build_report_command(qa_iso_path), capture_output=True, text=True, check=False
    )
    if report_result.returncode != 0:
        raise IsoPrepError(f"el-torito report for {qa_iso_path} failed: {report_result.stderr}")
    boot_flags = parse_el_torito_report(report_result.stdout)

    autoinstall_path = extracted_dir / "autoinstall.yaml"
    autoinstall_path.write_text(autoinstall_yaml_text, encoding="utf-8")

    output_iso.parent.mkdir(parents=True, exist_ok=True)
    rebuild_cmd = build_rebuild_command(extracted_dir, boot_flags, output_iso, VOLUME_ID)
    rebuild_result = subprocess_runner(  # type: ignore[operator]
        rebuild_cmd, capture_output=True, text=True, check=False
    )
    if rebuild_result.returncode != 0:
        raise IsoPrepError(f"rebuild of {output_iso} failed: {rebuild_result.stderr}")

    return output_iso
