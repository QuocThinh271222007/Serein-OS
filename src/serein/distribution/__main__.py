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
        manifest = run_build(source_commit=args.source_commit)
    except BuildError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(f"PASS: built {manifest.output.filename} sha256={manifest.output.sha256}")
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
    from serein.distribution.inspect import inspect_extracted_tree, inspect_iso_file

    target = Path(args.path)
    report = inspect_iso_file(target) if target.is_file() else inspect_extracted_tree(target)

    for finding in report.findings:
        print(f"[{finding.status.upper():4}] {finding.check}: {finding.detail}")
    print("PASSED" if report.passed else "FAILED")
    return 0 if report.passed else 1


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
    inspect_parser.set_defaults(func=_cmd_inspect)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
