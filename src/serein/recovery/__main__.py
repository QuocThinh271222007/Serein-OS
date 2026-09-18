"""``python -m serein.recovery repair --allow-repair`` - the one
mutating recovery entrypoint. Mirrors
``serein.firstboot.__main__``/``serein.installer.__main__``'s own
established separation of a distinct mutating entrypoint from the
read-only main CLI (``serein recovery status|doctor|plan``)."""

from __future__ import annotations

import argparse
import json
import sys

from .repair import RecoveryRepairError, repair_managed_files


def _cmd_repair(args: argparse.Namespace) -> int:
    try:
        report = repair_managed_files(allow_repair=args.allow_repair)
    except RecoveryRepairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print("SEREIN RECOVERY REPAIR")
        print()
        for result in report.results:
            status = "repaired" if result.repaired else "unchanged/failed"
            print(f"  [{status:17}] {result.target_path} - {result.detail}")
    return 0 if report.all_repaired else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m serein.recovery")
    subparsers = parser.add_subparsers(dest="command", required=True)

    repair_parser = subparsers.add_parser(
        "repair", help="Regenerate any managed file this system can independently repair"
    )
    repair_parser.add_argument(
        "--allow-repair", action="store_true",
        help="Explicit acknowledgement required to actually write anything (Section 38)",
    )
    repair_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    repair_parser.set_defaults(func=_cmd_repair)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
