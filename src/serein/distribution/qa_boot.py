"""QA-only serial boot variant (S7.0R Corrective B).

A template GRUB entry existing in Git (``distribution/boot/qa-serial-entry.cfg``)
never proves the *built* media actually selects it - this module makes
that real. It builds a second, QA-only ISO
(``serein-alpha-<release>-<arch>-qa.iso``) from the **same** extracted
base + overlay + payload as the canonical production ISO
(``serein.distribution.build.run_build`` copies the already-assembled
production extraction tree rather than re-extracting/re-overlaying), and
patches only the discovered GRUB boot configuration to:

- add a new, distinctly-titled QA menu entry that reuses the *real*
  ``linux``/``initrd`` paths found in the base image's own default
  entry (never guessed),
- route console output to the serial port (``console=ttyS0,115200n8``),
- select that entry automatically (``set default=0`` + a short
  ``set timeout``) so the boot-smoke harness never needs keyboard
  automation,
- never add ``autoinstall`` and never touch any disk target.

GRUB config discovery is fail-closed (Section 14): if none of the
known candidate paths exist in the extracted tree,
:func:`discover_grub_config` raises :class:`QaBootError` rather than
guessing a path from an old tutorial. The canonical production ISO is
completely unaffected - it is built first, from its own untouched
extraction, before this module ever runs.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Candidate GRUB config locations, most to least common on a modern
#: Ubuntu Desktop hybrid ISO's ISO9660 tree. Checked in order; the
#: first that exists wins. Never assumed present without checking
#: (Section 14).
GRUB_CONFIG_CANDIDATES: tuple[str, ...] = (
    "boot/grub/grub.cfg",
    "boot/grub/loopback.cfg",
    "EFI/boot/grub.cfg",
    "efi/boot/grub.cfg",
)

_MENUENTRY_RE = re.compile(r'menuentry\s+["\']([^"\']*)["\'][^{]*\{', re.IGNORECASE)
_LINUX_LINE_RE = re.compile(r"^(\s*linux(?:efi)?\s+)(\S+)(.*)$", re.IGNORECASE | re.MULTILINE)
_INITRD_LINE_RE = re.compile(r"^(\s*initrd(?:efi)?\s+)(\S+)(.*)$", re.IGNORECASE | re.MULTILINE)

QA_ENTRY_TITLE = "Serein Alpha (qa-serial-boot-smoke)"


class QaBootError(ValueError):
    """Raised when a QA boot variant cannot be safely prepared - e.g.
    no known GRUB config candidate exists in the extracted tree
    (``QA_BUILD=BLOCKED``, never guessed - Section 14)."""


@dataclass(frozen=True)
class QaVariantResult:
    qa_extracted_dir: Path
    grub_config_relative_path: str
    qa_entry_title: str
    checksum_catalog_updated: bool


def discover_grub_config(extracted_dir: Path) -> str:
    """Return the relative path (POSIX) of the first existing GRUB
    config candidate. Raises :class:`QaBootError` if none exist -
    fail-closed candidate discovery, never a hardcoded assumption."""
    for candidate in GRUB_CONFIG_CANDIDATES:
        if (extracted_dir / candidate).is_file():
            return candidate
    raise QaBootError(
        f"no known GRUB config candidate found under {extracted_dir} "
        f"(checked {GRUB_CONFIG_CANDIDATES}) - QA_BUILD=BLOCKED"
    )


def _remove_quiet(args: str) -> str:
    """Drop a standalone ``quiet`` kernel-cmdline token (Section 15
    prefers status-visible boot for positive-marker capture) without
    disturbing anything else on the line, including a trailing ``---``
    init-arg separator."""
    return re.sub(r"(?<!\S)quiet(?!\S)\s*", "", args)


def _add_serial_console(args: str, token: str = "console=ttyS0,115200n8") -> str:
    """Insert ``token`` as a kernel boot parameter - i.e. *before* a
    ``---`` separator if one is present, never after it (anything after
    ``---`` is passed to the init process, not the kernel, on a casper
    live boot line)."""
    if token in args:
        return args
    if "---" in args:
        before, sep, after = args.partition("---")
        return f"{before.rstrip()} {token} {sep}{after}"
    return f"{args.rstrip()} {token}"


def derive_qa_menuentry(grub_cfg_text: str, qa_entry_title: str = QA_ENTRY_TITLE) -> str:
    """Build a new QA menu-entry block reusing the real ``linux``/
    ``initrd`` lines from the first existing production entry, with
    serial routing added and ``quiet`` removed (Section 15). Never
    invents a kernel/initrd path - raises :class:`QaBootError` if no
    ``menuentry`` with both a ``linux``/``linuxefi`` and an
    ``initrd``/``initrdefi`` line can be found to derive from."""
    matches = list(_MENUENTRY_RE.finditer(grub_cfg_text))
    if not matches:
        raise QaBootError("no menuentry block found to derive a QA entry from")

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(grub_cfg_text)
        body = grub_cfg_text[start:end]

        linux_match = _LINUX_LINE_RE.search(body)
        initrd_match = _INITRD_LINE_RE.search(body)
        if not linux_match or not initrd_match:
            continue

        linux_directive, linux_path, linux_args = linux_match.groups()
        initrd_directive, initrd_path, initrd_args = initrd_match.groups()

        args = _add_serial_console(_remove_quiet(linux_args))
        if "autoinstall" in args:
            raise QaBootError(
                "refusing to derive a QA entry from a production entry that already "
                "carries autoinstall - this would need explicit human review"
            )

        return (
            f'menuentry "{qa_entry_title}" {{\n'
            f"{linux_directive}{linux_path}{args}\n"
            f"{initrd_directive}{initrd_path}{initrd_args}\n"
            f"}}\n"
        )

    raise QaBootError(
        "no menuentry with both a linux and initrd line found to derive a QA entry from"
    )


def install_qa_entry_as_default(grub_cfg_text: str, qa_entry_text: str) -> str:
    """Prepend the QA entry and force it to boot automatically -
    ``set default=0`` + a short ``set timeout`` (Section 17: "QA
    variant sets QA entry as temporary default"), never relying on
    keyboard automation."""
    prelude = 'set default="0"\nset timeout=1\n\n'
    body_without_defaults = re.sub(r"^set default=.*$", "", grub_cfg_text, flags=re.MULTILINE)
    body_without_defaults = re.sub(
        r"^set timeout=.*$", "", body_without_defaults, flags=re.MULTILINE
    )
    return prelude + qa_entry_text + "\n" + body_without_defaults


def update_checksum_catalog_if_present(tree_root: Path, modified_relative_path: str) -> bool:
    """If ``tree_root`` contains a top-level ``md5sum.txt`` (Ubuntu's
    real internal checksum catalog - Section 18), recompute the
    modified file's line so no stale checksum remains. Returns whether
    a catalog was found and updated - ``False`` (not an error) if no
    catalog exists at that conventional path, since not every base
    image is guaranteed to ship one there.
    """
    catalog_path = tree_root / "md5sum.txt"
    if not catalog_path.is_file():
        return False

    normalized_target = modified_relative_path.lstrip("./")
    lines = catalog_path.read_text(encoding="utf-8", errors="replace").splitlines()
    updated = False
    new_lines = []
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) == 2:
            _old_hash, entry_path = parts
            if entry_path.strip().lstrip("./") == normalized_target:
                new_digest = hashlib.md5(  # noqa: S324 - matching Ubuntu's own md5sum.txt format
                    (tree_root / normalized_target).read_bytes()
                ).hexdigest()
                new_lines.append(f"{new_digest}  ./{normalized_target}")
                updated = True
                continue
        new_lines.append(line)

    if updated:
        catalog_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def prepare_qa_variant(extracted_dir: Path, qa_extracted_dir: Path) -> QaVariantResult:
    """Copy the already-assembled production extraction tree and patch
    only its GRUB boot configuration to add and auto-select a QA serial
    entry. The production tree at ``extracted_dir`` is never modified.
    """
    if qa_extracted_dir.exists():
        shutil.rmtree(qa_extracted_dir)
    shutil.copytree(extracted_dir, qa_extracted_dir)

    grub_relative = discover_grub_config(qa_extracted_dir)
    grub_path = qa_extracted_dir / grub_relative
    original_text = grub_path.read_text(encoding="utf-8")

    qa_entry_text = derive_qa_menuentry(original_text)
    patched_text = install_qa_entry_as_default(original_text, qa_entry_text)
    grub_path.write_text(patched_text, encoding="utf-8")

    catalog_updated = update_checksum_catalog_if_present(qa_extracted_dir, grub_relative)

    return QaVariantResult(
        qa_extracted_dir=qa_extracted_dir,
        grub_config_relative_path=grub_relative,
        qa_entry_title=QA_ENTRY_TITLE,
        checksum_catalog_updated=catalog_updated,
    )
