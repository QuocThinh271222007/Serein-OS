"""``python -m serein.installer`` - the explicit, QA-CI-only installer
tooling entrypoint (S7.1 Sections 3, 23, 42-43).

Deliberately separate from the main ``serein`` CLI: the main CLI only
ever exposes read-only ``installer status``/``disks``/``doctor``/
``plan`` (Section 23-24 - "do not add a casual command that immediately
destroys storage"). Everything here is explicit, heavy tooling the
Layer-B GitHub Actions workflow runs on purpose - never invoked by
``pytest``/``ruff``/``mypy``/``verify.sh`` or the main CLI, and never
runs a destructive operation itself: it renders configuration and
assembles evidence; the actual real installation happens by booting a
prepared QA-install ISO under real QEMU (a separate shell step), the
same way ``serein.distribution``'s ``boot-smoke`` subcommand launches
QEMU for boot validation rather than this module doing so directly.

Subcommands:

    render-autoinstall     build+validate a plan from explicit target/
                            protected identities and render
                            autoinstall.yaml + install-state.json
                            (QA-only - requires --qa-allow-autoinstall)
    prepare-qa-install-iso extract a built QA ISO, embed a rendered
                            autoinstall.yaml, rebuild the QA-install
                            variant
    boot-check              boot the INSTALLED target disk on its own
                            (no install medium attached) and require a
                            genuine reached-target marker
    evidence                assemble the compact Installer Layer-B
                            evidence JSON (tolerant of partial/failed
                            runs)
    closure-gate            the one explicit, fail-closed Installer
                            Layer-B closure check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_protected_disk(spec: str) -> tuple[str, str]:
    """Parse one ``--protected-disk <serial>:<device_path>`` entry."""
    if ":" not in spec:
        raise argparse.ArgumentTypeError(
            f"--protected-disk must be 'SERIAL:DEVICE_PATH', got {spec!r}"
        )
    serial, device_path = spec.split(":", 1)
    if not serial or not device_path:
        raise argparse.ArgumentTypeError(
            f"--protected-disk must be 'SERIAL:DEVICE_PATH', got {spec!r}"
        )
    return serial, device_path


def _cmd_render_autoinstall(args: argparse.Namespace) -> int:
    from serein.installer.models import TargetDiskIdentity
    from serein.installer.payload import build_install_state_marker, generate_qa_credential
    from serein.installer.planner import build_install_plan, validate_plan
    from serein.installer.renderer import RendererError, render_autoinstall_yaml

    if not args.qa_allow_autoinstall:
        print(
            "FAIL: render-autoinstall refuses to run without --qa-allow-autoinstall - "
            "production media must never carry autoinstall (Section 6)",
            file=sys.stderr,
        )
        return 1

    target_identity = TargetDiskIdentity(
        serial=args.target_serial or None,
        wwn=args.target_wwn or None,
        model=args.target_model or None,
        size_bytes=args.target_size_bytes,
        observed_device_path=args.target_device_path,
    )
    protected_identities = tuple(
        TargetDiskIdentity(serial=serial, observed_device_path=device_path)
        for serial, device_path in (args.protected_disk or [])
    )
    protected_device_paths = tuple(
        device_path for _serial, device_path in (args.protected_disk or [])
    )

    plan = build_install_plan(
        target_identity, args.target_device_path, protected_disk_identities=protected_identities
    )
    validated = validate_plan(plan, protected_device_paths)
    if not validated.validation.valid:
        print(f"FAIL: PLAN_ESCAPE: plan invalid: {validated.validation.reasons}", file=sys.stderr)
        return 1

    credential = generate_qa_credential()
    if credential is None:
        print("FAIL: INSTALLER_UNAVAILABLE: could not generate a QA credential (openssl "
              "unavailable) - refusing to render without one", file=sys.stderr)
        return 1

    install_state = build_install_state_marker(
        source_commit=args.source_commit, source_media_version=args.source_media_version
    )

    try:
        rendered = render_autoinstall_yaml(
            validated, credential, install_state, qa_mode=True
        )
    except RendererError as exc:
        print(f"FAIL: INSTALLER_CONFIG_INVALID: {exc}", file=sys.stderr)
        return 1

    out_path = Path(args.out_yaml)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")

    if args.out_plan:
        plan_path = Path(args.out_plan)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(validated.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # Never print the credential - Section 35: "do not print the
    # credential unnecessarily into logs."
    print(f"PASS: wrote {out_path} (plan valid, QA credential generated at runtime)")
    return 0


def _cmd_prepare_qa_install_iso(args: argparse.Namespace) -> int:
    from serein.installer.isoprep import IsoPrepError, prepare_qa_install_iso

    autoinstall_text = Path(args.autoinstall_yaml).read_text(encoding="utf-8")
    try:
        output = prepare_qa_install_iso(
            qa_iso_path=Path(args.qa_iso),
            work_dir=Path(args.work_dir),
            output_iso=Path(args.out),
            autoinstall_yaml_text=autoinstall_text,
        )
    except IsoPrepError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: wrote {output}")
    return 0


def _cmd_boot_check(args: argparse.Namespace) -> int:
    import json as json_module

    from serein.installer.bootcheck import (
        default_timeout_seconds_for_accel,
        run_installed_disk_boot_check,
    )

    target_disk = Path(args.target_disk)
    work_dir = Path(args.work_dir) if args.work_dir else target_disk.parent / "installed-boot"
    ovmf_code = Path(args.ovmf_code) if args.ovmf_code else None

    if args.require_uefi and ovmf_code is None:
        print(
            "FAIL: --require-uefi set but no --ovmf-code given - "
            "REAL_INSTALLED_BOOT_MODE=BLOCKED",
            file=sys.stderr,
        )
        return 1

    result = run_installed_disk_boot_check(
        target_disk_path=target_disk,
        work_dir=work_dir,
        timeout_seconds=args.timeout or default_timeout_seconds_for_accel(args.accel),
        accel=args.accel,
        ovmf_code=ovmf_code,
        extra_disk_paths=tuple(Path(p) for p in (args.extra_disk or [])),
    )
    print(
        f"status={result.status} boot_mode={result.boot_mode} "
        f"marker={result.matched_marker!r} reason={result.reason}"
    )

    if args.result_json:
        result_path = Path(args.result_json)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json_module.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        )

    if result.status != "pass":
        print("--- log excerpt ---", file=sys.stderr)
        print(result.log_excerpt, file=sys.stderr)
    return 0 if result.status == "pass" else 1


def _load_json_optional(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _cmd_evidence(args: argparse.Namespace) -> int:
    from serein.installer.evidence import (
        assemble_installer_layer_b_evidence,
        write_installer_layer_b_evidence,
    )
    from serein.installer.models import TargetDiskIdentity

    target_identity = None
    if args.target_serial or args.target_device_path:
        target_identity = TargetDiskIdentity(
            serial=args.target_serial or None,
            observed_device_path=args.target_device_path or None,
        )
    protected_identities = tuple(
        TargetDiskIdentity(serial=serial, observed_device_path=device_path)
        for serial, device_path in (args.protected_disk or [])
    )

    boot_result = _load_json_optional(args.installed_boot_result)

    evidence = assemble_installer_layer_b_evidence(
        source_commit=args.source_commit,
        failure_stage=args.failure_stage,
        failure_reason=args.failure_reason,
        installer_backend=args.installer_backend or None,
        installer_backend_version=args.installer_backend_version or None,
        installer_backend_available=args.installer_backend_available,
        target_explicit=args.target_explicit,
        target_identity=target_identity,
        target_identity_revalidated=args.target_identity_revalidated,
        protected_disk_identities=protected_identities,
        plan_valid=args.plan_valid,
        all_destructive_ops_on_target=args.all_destructive_ops_on_target,
        target_disk_before_sha256=args.target_disk_before_sha256 or None,
        target_disk_after_sha256=args.target_disk_after_sha256 or None,
        protected_disk_before_sha256=tuple(args.protected_before_sha256 or ()),
        protected_disk_after_sha256=tuple(args.protected_after_sha256 or ()),
        target_esp_present=args.target_esp_present,
        target_root_present=args.target_root_present,
        protected_esp_unchanged=args.protected_esp_unchanged,
        installation_status=args.installation_status,
        install_media_removed_for_boot=args.install_media_removed_for_boot,
        installed_boot_status=(
            boot_result["status"] if boot_result else args.installed_boot_status
        ),
        installed_boot_mode=boot_result["boot_mode"] if boot_result else None,
        installed_boot_marker=boot_result["matched_marker"] if boot_result else None,
        install_media_attached_during_installed_boot=(
            args.install_media_attached_during_installed_boot
        ),
        serein_core_present=args.serein_core_present,
        firstboot_provisioning=args.firstboot_provisioning,
        autoinstall_mode=args.autoinstall_mode,
        target_disk_attached=args.target_disk_attached,
    )
    out_path = write_installer_layer_b_evidence(evidence, Path(args.out))
    print(f"PASS: wrote {out_path}")
    return 0


def _cmd_closure_gate(args: argparse.Namespace) -> int:
    from serein.installer.closure import ClosureError, enforce_installer_layer_b_closure
    from serein.installer.evidence import load_installer_layer_b_evidence

    evidence = load_installer_layer_b_evidence(Path(args.evidence))
    try:
        enforce_installer_layer_b_closure(
            evidence, expected_source_commit=args.expected_source_commit
        )
    except ClosureError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: Installer Layer-B closure gate satisfied")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m serein.installer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser(
        "render-autoinstall",
        help="Build+validate a plan and render autoinstall.yaml (QA-only)",
    )
    render_parser.add_argument("--target-device-path", required=True)
    render_parser.add_argument("--target-serial", default="")
    render_parser.add_argument("--target-wwn", default="")
    render_parser.add_argument("--target-model", default="")
    render_parser.add_argument("--target-size-bytes", type=int, default=None)
    render_parser.add_argument(
        "--protected-disk", action="append", type=_parse_protected_disk, default=[],
        help="'SERIAL:DEVICE_PATH' - repeatable, one per protected disk",
    )
    render_parser.add_argument("--source-commit", required=True)
    render_parser.add_argument("--source-media-version", required=True)
    render_parser.add_argument("--out-yaml", required=True)
    render_parser.add_argument("--out-plan", default=None)
    render_parser.add_argument(
        "--qa-allow-autoinstall", action="store_true",
        help="Required tripwire - never set this for a production path",
    )
    render_parser.set_defaults(func=_cmd_render_autoinstall)

    prepare_parser = subparsers.add_parser(
        "prepare-qa-install-iso", help="Embed a rendered autoinstall.yaml into a QA ISO variant"
    )
    prepare_parser.add_argument("--qa-iso", required=True)
    prepare_parser.add_argument("--autoinstall-yaml", required=True)
    prepare_parser.add_argument("--work-dir", required=True)
    prepare_parser.add_argument("--out", required=True)
    prepare_parser.set_defaults(func=_cmd_prepare_qa_install_iso)

    boot_check_parser = subparsers.add_parser(
        "boot-check",
        help="Boot the installed target disk on its own and require a genuine boot marker",
    )
    boot_check_parser.add_argument(
        "--target-disk", required=True, help="Path to the target disk image"
    )
    boot_check_parser.add_argument("--work-dir", default=None, help="Scratch directory for logs")
    boot_check_parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    boot_check_parser.add_argument("--accel", default="tcg", choices=["tcg", "kvm"])
    boot_check_parser.add_argument(
        "--ovmf-code", default=None, help="Path to OVMF_CODE.fd for UEFI boot"
    )
    boot_check_parser.add_argument(
        "--require-uefi", action="store_true",
        help="Fail before launching QEMU if --ovmf-code was not given",
    )
    boot_check_parser.add_argument(
        "--extra-disk", action="append", default=[],
        help="Attach an additional disk image (e.g. the protected-disk fixture) alongside the "
             "target - repeatable; never the boot device itself (Section 15)",
    )
    boot_check_parser.add_argument(
        "--result-json", default=None, help="Path to write a machine-readable boot-check result"
    )
    boot_check_parser.set_defaults(func=_cmd_boot_check)

    evidence_parser = subparsers.add_parser(
        "evidence", help="Assemble the compact Installer Layer-B evidence JSON"
    )
    evidence_parser.add_argument("--source-commit", required=True)
    evidence_parser.add_argument("--failure-stage", default=None)
    evidence_parser.add_argument("--failure-reason", default=None)
    evidence_parser.add_argument("--installer-backend", default="")
    evidence_parser.add_argument("--installer-backend-version", default="")
    evidence_parser.add_argument("--installer-backend-available", action="store_true")
    evidence_parser.add_argument("--target-explicit", action="store_true")
    evidence_parser.add_argument("--target-serial", default="")
    evidence_parser.add_argument("--target-device-path", default="")
    evidence_parser.add_argument("--target-identity-revalidated", action="store_true")
    evidence_parser.add_argument(
        "--target-disk-attached", action="store_true",
        help="Only set once the real fixture-disk topology was observed to exist "
             "(S7.1R Corrective B) - never a structural default",
    )
    evidence_parser.add_argument(
        "--protected-disk", action="append", type=_parse_protected_disk, default=[]
    )
    evidence_parser.add_argument("--plan-valid", action="store_true")
    evidence_parser.add_argument("--all-destructive-ops-on-target", action="store_true")
    evidence_parser.add_argument("--target-disk-before-sha256", default="")
    evidence_parser.add_argument("--target-disk-after-sha256", default="")
    evidence_parser.add_argument("--protected-before-sha256", action="append", default=[])
    evidence_parser.add_argument("--protected-after-sha256", action="append", default=[])
    evidence_parser.add_argument("--target-esp-present", action="store_true")
    evidence_parser.add_argument("--target-root-present", action="store_true")
    evidence_parser.add_argument("--protected-esp-unchanged", action="store_true")
    evidence_parser.add_argument(
        "--installation-status", default="not_performed",
        choices=["pass", "fail", "not_performed"],
    )
    evidence_parser.add_argument("--install-media-removed-for-boot", action="store_true")
    evidence_parser.add_argument("--installed-boot-result", default=None)
    evidence_parser.add_argument(
        "--installed-boot-status", default="not_performed",
        choices=["pass", "fail", "not_performed"],
        help="Used only if --installed-boot-result was not given",
    )
    evidence_parser.add_argument(
        "--install-media-attached-during-installed-boot", action="store_true"
    )
    evidence_parser.add_argument("--serein-core-present", action="store_true")
    evidence_parser.add_argument(
        "--firstboot-provisioning", default="unknown",
        choices=["pending", "complete", "unknown"],
    )
    evidence_parser.add_argument(
        "--autoinstall-mode", default="qa_only", choices=["qa_only", "production"]
    )
    evidence_parser.add_argument("--out", required=True)
    evidence_parser.set_defaults(func=_cmd_evidence)

    closure_gate_parser = subparsers.add_parser(
        "closure-gate", help="Enforce the explicit fail-closed Installer Layer-B closure gate"
    )
    closure_gate_parser.add_argument("--evidence", required=True)
    closure_gate_parser.add_argument("--expected-source-commit", required=True)
    closure_gate_parser.set_defaults(func=_cmd_closure_gate)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
