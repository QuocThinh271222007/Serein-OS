"""``python -m serein.distribution`` - the explicit distribution build
tooling entrypoint (S7.0 Section 13, 78).

Deliberately separate from the main ``serein`` CLI: the main CLI only
ever exposes read-only ``distribution status``/``distribution inspect``
(Section 78 - "do not add a command that downloads/builds multi-GB
media implicitly"). Everything here is explicit, heavy tooling a
developer runs on purpose - never invoked by ``pytest``/``ruff``/
``mypy``/``verify.sh`` or the main CLI.

Subcommands:

    verify-base    verify the cached base ISO's checksum (fail closed)
    build          run the full ISO build pipeline
    boot-smoke     bounded, marker-aware QEMU boot validation
    inspect PATH   structurally inspect a built ISO or extracted tree
    evidence       assemble the compact Layer-B evidence JSON (tolerant
                   of partial/failed runs - S7.0RM Corrective B)
    closure-gate   the one explicit, fail-closed Layer-B closure check
                   (S7.0RM Corrective G)
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
        result = run_build(
            source_commit=args.source_commit, ephemeral_storage=args.ephemeral_storage
        )
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
    import json

    from serein.distribution.bootsmoke import default_timeout_seconds_for_accel, run_boot_smoke

    iso_path = Path(args.iso)
    work_dir = Path(args.work_dir) if args.work_dir else iso_path.parent / "boot-smoke"
    ovmf_code = Path(args.ovmf_code) if args.ovmf_code else None

    if args.require_uefi and ovmf_code is None:
        # Corrective F: S7.0 closure requires real UEFI evidence - never
        # silently fall back to BIOS while a caller downstream might
        # still label the result "uefi". Fail closed before even
        # launching QEMU.
        print(
            "FAIL: --require-uefi set but no --ovmf-code given - REAL_UEFI_BOOT=BLOCKED",
            file=sys.stderr,
        )
        return 1

    # S7.0RM6 Corrective D/Section 11: TCG (software emulation) gets a
    # longer, still-bounded default timeout than KVM - an explicit
    # --timeout always overrides this.
    result = run_boot_smoke(
        iso_path=iso_path,
        work_dir=work_dir,
        timeout_seconds=args.timeout or default_timeout_seconds_for_accel(args.accel),
        accel=args.accel,
        ovmf_code=ovmf_code,
    )
    print(
        f"status={result.status} boot_mode={result.boot_mode} "
        f"marker={result.matched_marker!r} reason={result.reason}"
    )

    if args.result_json:
        result_path = Path(args.result_json)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")

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
        # S7.0RM6 Corrective A: scoped by the ISO's own filename stem
        # so two independent strict inspections (e.g. production then
        # QA) never default to sharing one mutable scratch subtree - a
        # real run crashed with PermissionError when the QA inspection
        # tried to delete the production inspection's own leftover
        # extraction. A caller may still pass --work-dir explicitly for
        # its own isolation scheme.
        work_dir = (
            Path(args.work_dir) if args.work_dir
            else target.parent / "inspect-strict-work" / target.stem
        )
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

    def _load_json_optional(path: str | None) -> dict | None:
        # Corrective B: never assume a stage's file exists - an earlier
        # failure (e.g. the disk-space preflight, before any build)
        # means the production/QA manifest legitimately never got
        # written. Missing means "that stage did not happen", not a
        # crash.
        if not path:
            return None
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    prod = _load_json_optional(args.production_manifest)
    qa = _load_json_optional(args.qa_manifest)
    boot_result = _load_json_optional(args.boot_smoke_result)

    failure_stage = args.failure_stage
    failure_reason = args.failure_reason
    production_build = args.production_build
    qa_transition = args.qa_transition
    qa_build = args.qa_build

    # S7.0RM5 Corrective B: when the build-stage marker exists, it is
    # ground truth for these three fields - finer-grained than any
    # single combined GitHub Actions step outcome could ever be (a real
    # run proved production can fully succeed while a later QA
    # transition still fails within the SAME shell step). Absent
    # entirely (e.g. an even earlier failure before run_build() ever
    # started) means the plain --production-build/--qa-transition/
    # --qa-build flags below are all that is known, unchanged from
    # before this corrective.
    if args.build_stage_status and Path(args.build_stage_status).is_file():
        from serein.distribution.build import load_build_stage_status

        stage_status = load_build_stage_status(Path(args.build_stage_status))
        production_build = stage_status.production_build
        qa_transition = stage_status.qa_transition
        qa_build = stage_status.qa_build
        if stage_status.failure_stage:
            failure_stage = stage_status.failure_stage
            failure_reason = stage_status.failure_reason

    evidence = assemble_layer_b_evidence(
        source_commit=args.source_commit,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        base_filename=args.base_filename or None,
        base_sha256_expected=args.base_sha256_expected or None,
        base_sha256_actual=args.base_sha256_actual or None,
        production_iso_filename=prod["output"]["filename"] if prod else None,
        production_iso_sha256=prod["output"]["sha256"] if prod else None,
        production_build=production_build,
        production_inspection=args.production_inspection,
        qa_transition=qa_transition,
        qa_iso_filename=qa["output"]["filename"] if qa else None,
        qa_iso_sha256=qa["output"]["sha256"] if qa else None,
        qa_build=qa_build,
        qa_inspection=args.qa_inspection,
        qemu_boot=boot_result["status"] if boot_result else args.qemu_boot,
        qemu_boot_mode=boot_result["boot_mode"] if boot_result else None,
        ovmf_firmware=boot_result.get("firmware") if boot_result else None,
        boot_marker=boot_result["matched_marker"] if boot_result else None,
    )
    out_path = write_layer_b_evidence(evidence, Path(args.out))
    print(f"PASS: wrote {out_path}")
    return 0


def _cmd_closure_gate(args: argparse.Namespace) -> int:
    from serein.distribution.closure import ClosureError, enforce_layer_b_closure
    from serein.distribution.evidence import load_layer_b_evidence

    evidence = load_layer_b_evidence(Path(args.evidence))
    try:
        enforce_layer_b_closure(evidence, expected_source_commit=args.expected_source_commit)
    except ClosureError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: Layer-B closure gate satisfied")
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
    build_parser.add_argument(
        "--ephemeral-storage", action="store_true",
        help="Delete the cached base ISO once no longer needed - ephemeral CI runners only, "
             "never a normal developer build",
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
    boot_smoke_parser.add_argument(
        "--require-uefi", action="store_true",
        help="Fail before launching QEMU if --ovmf-code was not given (never silently boot BIOS)",
    )
    boot_smoke_parser.add_argument(
        "--result-json", default=None, help="Path to write a machine-readable boot-smoke result"
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
        "evidence", help="Assemble the compact Layer-B evidence JSON (tolerant of partial runs)"
    )
    evidence_parser.add_argument(
        "--source-commit", required=True, help="Known from the exact-head checkout, always present"
    )
    evidence_parser.add_argument(
        "--failure-stage", default=None,
        help="Name of the stage that failed, if any (e.g. disk_preflight, base_verification)",
    )
    evidence_parser.add_argument("--failure-reason", default=None)
    evidence_parser.add_argument("--base-filename", default=None)
    evidence_parser.add_argument("--base-sha256-expected", default=None)
    evidence_parser.add_argument("--base-sha256-actual", default=None)
    evidence_parser.add_argument(
        "--production-manifest", default=None,
        help="Path to the production build manifest, if the build reached that stage",
    )
    evidence_parser.add_argument(
        "--production-build", default="not_performed", choices=["pass", "fail", "not_performed"]
    )
    evidence_parser.add_argument(
        "--production-inspection", default="not_performed",
        choices=["pass", "fail", "not_performed"],
    )
    evidence_parser.add_argument(
        "--qa-transition", default="not_performed", choices=["pass", "fail", "not_performed"],
        help="Overridden by --build-stage-status when that marker file exists",
    )
    evidence_parser.add_argument(
        "--build-stage-status", default=None,
        help="Path to the build-stage-status.json marker run_build() writes "
             "(S7.0RM5 Corrective B) - when present, its production_build/qa_transition/"
             "qa_build (and, if it recorded one, failure_stage/failure_reason) take "
             "precedence over the corresponding flags below, since a real run proved a "
             "single combined build step's outcome is too coarse to distinguish them",
    )
    evidence_parser.add_argument("--qa-manifest", default=None)
    evidence_parser.add_argument(
        "--qa-build", default="not_performed", choices=["pass", "fail", "not_performed"]
    )
    evidence_parser.add_argument(
        "--qa-inspection", default="not_performed", choices=["pass", "fail", "not_performed"]
    )
    evidence_parser.add_argument(
        "--boot-smoke-result", default=None,
        help="Path to the JSON result written by `boot-smoke --result-json`",
    )
    evidence_parser.add_argument(
        "--qemu-boot", default="not_performed", choices=["pass", "fail", "not_performed"],
        help="Used only if --boot-smoke-result was not given",
    )
    evidence_parser.add_argument("--out", required=True)
    evidence_parser.set_defaults(func=_cmd_evidence)

    closure_gate_parser = subparsers.add_parser(
        "closure-gate", help="Enforce the explicit fail-closed Layer-B closure gate"
    )
    closure_gate_parser.add_argument("--evidence", required=True, help="Path to the evidence JSON")
    closure_gate_parser.add_argument("--expected-source-commit", required=True)
    closure_gate_parser.set_defaults(func=_cmd_closure_gate)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
