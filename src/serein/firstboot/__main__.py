"""``python -m serein.firstboot`` - the explicit, heavy first-boot
provisioning entrypoint (Section 12).

Deliberately separate from the main ``serein`` CLI, mirroring
``serein.installer.__main__``'s own separation: the main CLI only ever
exposes read-only ``firstboot status``/``doctor``/``plan`` (see
``src/serein/cli.py``) - "do not add a casual command that immediately
mutates an installed system." The one real mutation entrypoint,
``run``, lives here, requires the explicit ``--allow-run`` tripwire (the
same discipline as the installer's ``--qa-allow-autoinstall``), and is
the command ``distribution/systemd/serein-firstboot.service`` actually
invokes at boot - never something a human runs casually from the
interactive CLI.
"""

from __future__ import annotations

import argparse
import json
import sys

from serein.hardware._util import DEFAULT_ROOT

from .engine import run_firstboot


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.allow_run:
        print(
            "FAIL: run refuses to execute without --allow-run - first-boot provisioning "
            "must never mutate a host by accident (Section 12/26)",
            file=sys.stderr,
        )
        return 1

    result = run_firstboot(root=DEFAULT_ROOT)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"status={result.status} mutated={result.mutated} reason={result.reason}")

    # A oneshot systemd unit exits 0 on anything that is not a genuine
    # in-run failure - BLOCKED/NOT_REQUIRED/LOCKED are all expected,
    # non-error outcomes on *some* boot (Section 11: "Do not create a
    # boot loop" / "Do not block earlier boot stages unnecessarily").
    return 1 if result.status == "FAILED" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m serein.firstboot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Execute first-boot provisioning (mutating - requires --allow-run)"
    )
    run_parser.add_argument(
        "--allow-run", action="store_true",
        help="Required tripwire - only the systemd unit or an explicit administrator "
             "should set this",
    )
    run_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    run_parser.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
