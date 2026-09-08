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

S7.1R3 fix (Run #3, RUN_ID=34224122883): placing ``autoinstall.yaml``
at the tree root was NEVER sufficient on its own - the QA ISO's
already-baked-in boot entry (``serein.distribution.qa_boot``'s
``QA_ENTRY_TITLE``, "Serein Alpha (qa-serial-boot-smoke)") is
explicitly documented and coded to NEVER carry the ``autoinstall``
kernel parameter, since that entry exists only to prove S7.0's own ISO
boots (a read-only smoke test - ``qa_boot.py``'s own module docstring:
"never add autoinstall and never touch any disk target"). Real Run #3
evidence proved the booted kernel command line was exactly
``BOOT_IMAGE=/casper/vmlinuz console=ttyS0,115200n8 --- splash`` - no
``autoinstall`` token anywhere - so Subiquity never entered unattended
mode at all; the medium booted into a completely normal interactive
live desktop session (matching every other observed Run #3 symptom:
the full stock snap set loading, the target disk never being touched,
and the run eventually exhausting its 1800s timeout).
``prepare_qa_install_iso`` now further patches ITS OWN independent
copy of the extracted tree to add the ``autoinstall`` kernel
parameter to that one specific boot entry - never touching
``serein.distribution.qa_boot`` itself, whose "never autoinstall"
contract must remain intact for S7.0's own boot-smoke use case.
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from serein.distribution.iso import (
    build_extract_command,
    build_rebuild_command,
    build_report_command,
    parse_el_torito_report,
)
from serein.distribution.models import VOLUME_ID
from serein.distribution.pathsafety import PathSafetyError, resolve_within
from serein.distribution.qa_boot import QA_ENTRY_TITLE, QaBootError, discover_grub_config


class IsoPrepError(RuntimeError):
    """Raised for any QA-install-ISO preparation failure - fail closed,
    never ship a half-prepared variant."""


class AutoinstallBootError(RuntimeError):
    """Raised when the QA-install ISO's boot configuration cannot be
    safely patched to trigger unattended autoinstall - fail closed.
    Mirrors ``serein.distribution.qa_boot.QaBootError``'s own
    "never guess, never ship a silently-broken boot entry" discipline,
    but is a distinct, S7.1-owned error type - never reuses or
    subclasses the S7.0 one, keeping the two subsystems'
    error-handling independent (Section 3-4)."""


_QA_MENUENTRY_RE = re.compile(r'menuentry\s+["\']([^"\']*)["\'][^{]*\{', re.IGNORECASE)
_LINUX_LINE_RE = re.compile(r"^(\s*linux(?:efi)?\s+)(\S+)(.*)$", re.IGNORECASE | re.MULTILINE)


@contextmanager
def _temporarily_owner_writable(path: Path) -> Iterator[None]:
    """Ensure ``path`` has its owner-write bit set for the duration of
    this context, then restore its exact original mode afterward - even
    if the body raises. An independently-owned, S7.1-scoped copy of the
    same tiny pattern ``serein.distribution.qa_boot`` uses for the
    identical real reason (S7.0RM5 Corrective A: a real Layer-B run hit
    ``PermissionError`` writing a non-owner-writable extracted file) -
    never imports the private helper across module boundaries; this
    operates only on isoprep's own extracted tree, never
    ``build/work/extracted``."""
    original_mode = stat.S_IMODE(path.stat().st_mode)
    try:
        if not original_mode & stat.S_IWUSR:
            path.chmod(original_mode | stat.S_IWUSR)
        yield
    finally:
        path.chmod(original_mode)


def _enable_autoinstall_on_qa_entry(
    grub_cfg_text: str, entry_title: str = QA_ENTRY_TITLE
) -> str:
    """Add the bare ``autoinstall`` kernel parameter to the named
    menuentry's ``linux``/``linuxefi`` line - the real, evidence-proven
    Run #3 fix (see this module's own docstring for the full causal
    chain). Inserted before a ``---`` init-arg separator if present
    (mirrors ``qa_boot._add_serial_console``'s own placement rule) -
    never after it, since anything after ``---`` is passed to the init
    process, not the kernel, on a casper live boot line.

    Idempotent: a no-op if ``autoinstall`` is already present, so
    re-running preparation twice never duplicates the token. Raises
    :class:`AutoinstallBootError` if the named entry, or a
    ``linux``/``linuxefi`` line inside it, cannot be found - never
    silently ships a QA-install ISO whose autoinstall trigger failed to
    attach.
    """
    matches = list(_QA_MENUENTRY_RE.finditer(grub_cfg_text))
    for index, match in enumerate(matches):
        if match.group(1) != entry_title:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(grub_cfg_text)
        body = grub_cfg_text[start:end]

        linux_match = _LINUX_LINE_RE.search(body)
        if not linux_match:
            raise AutoinstallBootError(
                f"menuentry {entry_title!r} has no linux/linuxefi line to patch - "
                "AUTOINSTALL_BOOT=BLOCKED"
            )
        directive, kernel_path, args = linux_match.groups()
        if re.search(r"(?<!\S)autoinstall(?!\S)", args):
            return grub_cfg_text  # already present - idempotent no-op

        if "---" in args:
            before, sep, after = args.partition("---")
            new_args = f"{before.rstrip()} autoinstall {sep}{after}"
        else:
            new_args = f"{args.rstrip()} autoinstall"
        new_line = f"{directive}{kernel_path}{new_args}"
        new_body = body[: linux_match.start()] + new_line + body[linux_match.end() :]
        return grub_cfg_text[:start] + new_body + grub_cfg_text[end:]

    raise AutoinstallBootError(
        f"no menuentry titled {entry_title!r} found in the extracted QA-install tree - "
        "AUTOINSTALL_BOOT=BLOCKED (S7.1R3)"
    )


def prepare_qa_install_iso(
    qa_iso_path: Path,
    work_dir: Path,
    output_iso: Path,
    autoinstall_yaml_text: str,
    subprocess_runner: object = subprocess.run,
) -> Path:
    """Extract ``qa_iso_path``, patch its boot entry to actually trigger
    unattended autoinstall (S7.1R3), write ``autoinstall_yaml_text`` at
    the tree root, and rebuild into ``output_iso``. ``subprocess_runner``
    is injectable (must accept the same positional/``check`` signature
    as ``subprocess.run``) so this whole pipeline is unit-testable with
    a fake ``xorriso`` - mirroring
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

    # S7.1R3: the proven real Run #3 fix - without this, the rebuilt
    # medium boots into a normal interactive live session and never
    # touches the target disk at all (see module docstring).
    try:
        grub_relative = discover_grub_config(extracted_dir)
    except QaBootError as exc:
        raise IsoPrepError(f"cannot enable autoinstall boot: {exc}") from exc
    try:
        grub_path = resolve_within(extracted_dir, grub_relative)
    except PathSafetyError as exc:
        raise IsoPrepError(
            f"cannot enable autoinstall boot: {grub_relative!r} escapes the "
            f"extraction root: {exc}"
        ) from exc
    original_grub_text = grub_path.read_text(encoding="utf-8")
    try:
        patched_grub_text = _enable_autoinstall_on_qa_entry(original_grub_text)
    except AutoinstallBootError as exc:
        raise IsoPrepError(f"cannot enable autoinstall boot: {exc}") from exc
    with _temporarily_owner_writable(grub_path):
        grub_path.write_text(patched_grub_text, encoding="utf-8")

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
