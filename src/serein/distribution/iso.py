"""ISO boot-flag derivation and rebuild-command construction (S7.0
Sections 35-38).

Boot flags are never copied from a tutorial (Section 39). They are
derived programmatically from the *actual selected ISO's* own
``xorriso -indev <base.iso> -report_el_torito as_mkisofs`` report -
``parse_el_torito_report`` just tokenizes whatever that report says at
build time, so the flags always match the real base image, not a
remembered/guessed set. Nothing in this module invokes ``xorriso``
itself; callers run the report/rebuild commands and pass the captured
text in, which keeps this module pure and unit-testable without the
tool installed.
"""

from __future__ import annotations

import shlex
from pathlib import Path


class IsoCommandError(ValueError):
    """Raised when an el-torito report cannot be parsed into flags."""


def parse_el_torito_report(report_text: str) -> list[str]:
    """Turn the line-oriented output of
    ``xorriso -indev <iso> -report_el_torito as_mkisofs`` into a flat
    argv-fragment list suitable for re-use on an ``xorriso -as mkisofs``
    rebuild command line.

    Each non-empty, non-comment line is itself already shaped like one
    or more xorriso command-line options (quoted where a value contains
    whitespace); this just applies POSIX-shell-style tokenization
    (``shlex``, respecting quotes) and concatenates the results in the
    report's own order - xorriso's boot flags are order-sensitive, and
    this preserves that order exactly rather than re-sorting or
    deduplicating anything.
    """
    flags: list[str] = []
    for line in report_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            flags.extend(shlex.split(stripped))
        except ValueError as exc:
            raise IsoCommandError(f"could not tokenize el-torito report line: {line!r}") from exc
    if not flags:
        raise IsoCommandError(
            "el-torito report produced no boot flags - refusing to build an "
            "ISO with an unknown/unverified boot catalog"
        )
    return flags


def build_report_command(base_iso: Path) -> list[str]:
    """The exact inspection command used to derive boot flags from the
    real base image (Section 38)."""
    return ["xorriso", "-indev", str(base_iso), "-report_el_torito", "as_mkisofs"]


#: Value-taking options the canonical Serein builder intentionally owns
#: and must never let a replayed upstream report override (S7.0RM4
#: Corrective C) - a real base image's own
#: ``-report_el_torito as_mkisofs`` output can contain the upstream
#: product's own ``-V "Ubuntu 26.04.1 LTS amd64"``/``-volid`` token,
#: which, replayed *after* Serein's own ``-V SEREIN_ALPHA`` in the
#: rebuild argv, would win (xorriso takes the last ``-V`` on the command
#: line) and silently retitle the final media. Every other reported
#: option (``--grub2-mbr``, ``--interval:local_fs:...``,
#: ``-append_partition``, ``-c``, ``-b``, etc.) is real boot-architecture
#: data and is never touched.
BUILDER_OWNED_VALUE_OPTIONS: frozenset[str] = frozenset({"-V", "-volid"})


def filter_builder_owned_boot_flags(
    flags: list[str], owned_options: frozenset[str] = BUILDER_OWNED_VALUE_OPTIONS
) -> list[str]:
    """Remove builder-owned metadata options (and their one value each)
    from a replayed el-torito report's flags, preserving the order and
    identity of every other flag untouched.

    Conservative by construction: only options in ``owned_options`` are
    ever removed - any option this function does not recognize is
    assumed to be real boot-architecture data and is preserved exactly
    (Section 4 of the S7.0RM4 corrective - "preserve unknown boot-related
    options by default"). Fails closed with :class:`IsoCommandError` if
    an owned option appears with no following value, rather than
    silently producing a corrupted argv.
    """
    filtered: list[str] = []
    index = 0
    while index < len(flags):
        token = flags[index]
        if token in owned_options:
            if index + 1 >= len(flags):
                raise IsoCommandError(
                    f"malformed el-torito report: {token!r} has no following value"
                )
            index += 2  # drop the option and its value, keep everything else
            continue
        filtered.append(token)
        index += 1
    return filtered


def build_rebuild_command(
    extracted_tree: Path,
    boot_flags: list[str],
    output_iso: Path,
    volume_id: str,
) -> list[str]:
    """Construct the ``xorriso -as mkisofs`` rebuild argv.

    ``boot_flags`` must come from :func:`parse_el_torito_report` against
    the actual selected base image - this function does not invent or
    default them, and raises if given an empty list, since an ISO built
    without any boot catalog is not valid distribution media. Any
    builder-owned metadata option (``-V``/``-volid``) the replayed
    report itself contains is filtered out first
    (:func:`filter_builder_owned_boot_flags`) so the final argv carries
    exactly one effective volume-ID contract - ``volume_id`` - never a
    later-and-therefore-winning upstream value (S7.0RM4 Corrective C).
    """
    if not boot_flags:
        raise IsoCommandError("refusing to build an ISO rebuild command with no boot flags")

    filtered_flags = filter_builder_owned_boot_flags(boot_flags)
    if not filtered_flags:
        raise IsoCommandError(
            "no real boot flags remained after filtering builder-owned metadata - "
            "refusing to build an ISO with an unknown/unverified boot catalog"
        )

    return [
        "xorriso", "-as", "mkisofs",
        "-V", volume_id,
        "-r", "-J", "-joliet-long",
        *filtered_flags,
        "-o", str(output_iso),
        str(extracted_tree),
    ]


def build_extract_command(base_iso: Path, dest_dir: Path) -> list[str]:
    """Read-only, rootless extraction of the base ISO's contents
    (Section 20) - ``xorriso -osirrox on`` copies out of the ISO
    filesystem without mounting it or requiring root."""
    return [
        "xorriso", "-osirrox", "on",
        "-indev", str(base_iso),
        "-extract", "/", str(dest_dir),
    ]
