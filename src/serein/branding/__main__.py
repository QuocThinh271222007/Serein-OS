"""``python -m serein.branding <command>`` - narrow, fast, offline
entrypoints meant to be shelled out to by external tools (Fastfetch's
own "command"-type module - Section 16), never by a human directly.
Deliberately separate from ``serein.cli`` (mirrors
``serein.installer.__main__``/``serein.firstboot.__main__``'s own
established separation) - a human-facing command belongs in the main
CLI; a machine-facing one-line-stdout helper does not.
"""

from __future__ import annotations

import argparse
import sys

from serein.branding.fastfetch import focus_display_label


def _cmd_focus_label(_args: argparse.Namespace) -> int:
    print(focus_display_label())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m serein.branding")
    subparsers = parser.add_subparsers(dest="command", required=True)

    focus_label_parser = subparsers.add_parser(
        "focus-label",
        help="Print the current Focus display label (for Fastfetch's command module)",
    )
    focus_label_parser.set_defaults(func=_cmd_focus_label)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
