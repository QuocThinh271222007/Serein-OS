"""``python -m serein.distribution`` - the explicit distribution build
tooling entrypoint (S7.0 Section 13, 78).

Deliberately separate from the main ``serein`` CLI: the main CLI only
ever exposes read-only ``distribution status``/``distribution inspect``
(Section 78 - "do not add a command that downloads/builds multi-GB
media implicitly"). Everything here is explicit, heavy tooling a
developer runs on purpose - never invoked by ``pytest``/``ruff``/
``mypy``/``verify.sh`` or the main CLI.

Subcommands:

    verify-base   verify the cached base ISO's checksum (fail closed)
    build         run the full ISO build pipeline
    inspect PATH  structurally inspect a built ISO or extracted tree
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_verify_base(_args: argparse.Namespace) -> int:
    from serein.distribution.base import BaseImageError, load_base_image_spec, verify_base_image
    from serein.distribution.status import CACHE_DIR

    try:
        spec = load_base_image_spec()
    except BaseImageError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    base_iso = CACHE_DIR / spec.filename
    try:
        verify_base_image(base_iso, spec)
    except BaseImageError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(f"PASS: {spec.filename} matches pinned sha256 {spec.sha256}")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from serein.distribution.build import BuildError, run_build

    try:
        result = run_build(source_commit=args.source_commit)
    except BuildError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    prod = result.production.output
    print(f"PASS: built {prod.filename} sha256={prod.sha256}")
    if result.qa is not None:
        qa = result.qa.output
        print(f"PASS: built QA variant {qa.filename} sha256={qa.sha256}")
    else:
        print(f"QA_BUILD=BLOCKED: {result.qa_blocked_reason}", file=sys.stderr)
    return 0


def _cmd_boot_smoke(args: argparse.Namespace) -> int:
    from serein.distribution.bootsmoke import DEFAULT_TIMEOUT_SECONDS, run_boot_smoke

    iso_path = Path(args.iso)
    work_dir = Path(args.work_dir) if args.work_dir else iso_path.parent / "boot-smoke"
    ovmf_code = Path(args.ovmf_code) if args.ovmf_code else None

    result = run_boot_smoke(
        iso_path=iso_path,
        work_dir=work_dir,
        timeout_seconds=args.timeout or DEFAULT_TIMEOUT_SECONDS,
        accel=args.accel,
        ovmf_code=ovmf_code,
    )
    print(f"status={result.status} marker={result.matched_marker!r} reason={result.reason}")
    if result.status != "pass":
        print("--- log excerpt ---", file=sys.stderr)
        print(result.log_excerpt, file=sys.stderr)
    return 0 if result.status == "pass" else 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    from serein.distribution.inspect import (
        inspect_extracted_tree,
        inspect_iso_file,
        inspect_iso_file_strict,
    )

    target = Path(args.path)

    if args.strict:
        if not args.expected_source_commit:
            print("FAIL: --strict requires --expected-source-commit", file=sys.stderr)
            return 1
        work_dir = Path(args.work_dir) if args.work_dir else target.parent / "inspect-strict-work"
        report = inspect_iso_file_strict(
            target, work_dir, expected_source_commit=args.expected_source_commit
        )
        for finding in report.findings:
            print(f"[{finding.status.upper():4}] {finding.check}: {finding.detail}")
        print("STRICT_PASSED" if report.strict_passed else "STRICT_FAILED")
        return 0 if report.strict_passed else 1

    report = inspect_iso_file(target) if target.is_file() else inspect_extracted_tree(target)
    for finding in report.findings:
        print(f"[{finding.status.upper():4}] {finding.check}: {finding.detail}")
    print("PASSED" if report.passed else "FAILED")
    return 0 if report.passed else 1


def _cmd_evidence(args: argparse.Namespace) -> int:
    import json

    from serein.distribution.evidence import assemble_layer_b_evidence, write_layer_b_evidence

    def _load_manifest_dict(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    prod = _load_manifest_dict(args.production_manifest)
    qa = _load_manifest_dict(args.qa_manifest) if args.qa_manifest else None

    evidence = assemble_layer_b_evidence(
        source_commit=prod["source_commit"],
        base_filename=args.base_filename,
        base_sha256_expected=args.base_sha256_expected,
        base_sha256_actual=args.base_sha256_actual,
        production_iso_filename=prod["output"]["filename"],
        production_iso_sha256=prod["output"]["sha256"],
        production_inspection_status=args.production_inspection_status,
        qa_boot_iso_filename=qa["output"]["filename"] if qa else None,
        qa_boot_iso_sha256=qa["output"]["sha256"] if qa else None,
        qemu_boot=args.qemu_boot_status,
        qemu_boot_mode=args.qemu_boot_mode,
        boot_marker=args.boot_marker,
    )
    out_path = write_layer_b_evidence(evidence, Path(args.out))
    print(f"PASS: wrote {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m serein.distribution")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "verify-base", help="Verify the cached base ISO's checksum"
    ).set_defaults(func=_cmd_verify_base)

    build_parser = subparsers.add_parser("build", help="Run the full ISO build pipeline")
    build_parser.add_argument(
        "--source-commit", required=True, help="Full git commit sha to record in the build manifest"
    )
    build_parser.set_defaults(func=_cmd_build)

    boot_smoke_parser = subparsers.add_parser(
        "boot-smoke", help="Run a bounded QEMU boot-smoke validation against a built ISO"
    )
    boot_smoke_parser.add_argument("--iso", required=True, help="Path to the built ISO")
    boot_smoke_parser.add_argument("--work-dir", default=None, help="Scratch directory for logs")
    boot_smoke_parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    boot_smoke_parser.add_argument("--accel", default="tcg", choices=["tcg", "kvm"])
    boot_smoke_parser.add_argument(
        "--ovmf-code", default=None, help="Path to OVMF_CODE.fd for UEFI boot"
    )
    boot_smoke_parser.set_defaults(func=_cmd_boot_smoke)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Structurally inspect a built ISO or extracted tree"
    )
    inspect_parser.add_argument("path", help="Path to a .iso file or an extracted tree directory")
    inspect_parser.add_argument(
        "--strict", action="store_true",
        help="Layer-B closure inspection - a skip fails just like a fail (real .iso only)",
    )
    inspect_parser.add_argument(
        "--expected-source-commit", default=None, help="Required with --strict"
    )
    inspect_parser.add_argument(
        "--work-dir", default=None, help="Scratch dir for --strict extraction"
    )
    inspect_parser.set_defaults(func=_cmd_inspect)

    evidence_parser = subparsers.add_parser(
        "evidence", help="Assemble the compact Layer-B evidence JSON"
    )
    evidence_parser.add_argument("--production-manifest", required=True)
    evidence_parser.add_argument("--qa-manifest", default=None)
    evidence_parser.add_argument("--base-filename", required=True)
    evidence_parser.add_argument("--base-sha256-expected", required=True)
    evidence_parser.add_argument("--base-sha256-actual", required=True)
    evidence_parser.add_argument(
        "--production-inspection-status", default="not_performed",
        choices=["pass", "fail", "not_performed"],
    )
    evidence_parser.add_argument(
        "--qemu-boot-status", default="not_performed", choices=["pass", "fail", "not_performed"]
    )
    evidence_parser.add_argument("--qemu-boot-mode", default=None, choices=[None, "uefi", "bios"])
    evidence_parser.add_argument("--boot-marker", default=None)
    evidence_parser.add_argument("--out", required=True)
    evidence_parser.set_defaults(func=_cmd_evidence)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
