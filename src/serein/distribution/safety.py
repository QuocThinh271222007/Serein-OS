"""Static safety regressions for distribution media content (S7.0
Sections 40-42, 87-88).

Two independent concerns live here, both purely textual/static - neither
boots anything, mounts anything, or requires the real ISO to exist:

- **Autoinstall safety** (Section 40-41, 87): production boot
  configuration must never trigger an unattended, disk-wiping install by
  default. A dedicated, clearly separate QA/automation boot entry may
  use ``autoinstall`` for VM validation only.
- **Credential scanning** (Section 42, 88): the distribution tree must
  never contain a plaintext password, private key, or token, with
  sensible allowlisting for documentation that merely *names* these
  patterns (like this file's own docstring).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: A boot-menu entry title containing any of these (case-insensitive) is
#: treated as a deliberately separate QA/automation entry, never the
#: production default (Section 47).
_QA_ENTRY_MARKERS = ("qa", "automation", "boot-smoke", "test")

_MENUENTRY_RE = re.compile(r'menuentry\s+["\']([^"\']*)["\'][^{]*\{', re.IGNORECASE)


@dataclass(frozen=True)
class AutoinstallFinding:
    entry_title: str
    reason: str


def scan_boot_config_for_default_autoinstall(grub_cfg_text: str) -> list[AutoinstallFinding]:
    """Parse a GRUB-style config into menu entries and flag any entry
    whose kernel command line contains ``autoinstall`` *unless* its
    title is clearly marked as a QA/automation entry (Section 47).

    A config with no ``menuentry`` blocks at all (e.g. a bare kernel
    command-line fragment) is scanned as a single implicit entry titled
    ``"(default)"`` so a bare ``autoinstall`` token anywhere is still
    caught.
    """
    findings: list[AutoinstallFinding] = []
    matches = list(_MENUENTRY_RE.finditer(grub_cfg_text))

    if not matches:
        if "autoinstall" in grub_cfg_text:
            findings.append(
                AutoinstallFinding(
                    entry_title="(default)",
                    reason="'autoinstall' present with no menu entries to scope it to a QA path",
                )
            )
        return findings

    for index, match in enumerate(matches):
        title = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(grub_cfg_text)
        body = grub_cfg_text[start:end]

        if "autoinstall" not in body:
            continue

        is_qa = any(marker in title.lower() for marker in _QA_ENTRY_MARKERS)
        if not is_qa:
            findings.append(
                AutoinstallFinding(
                    entry_title=title,
                    reason="'autoinstall' present on a boot entry not marked as QA/automation-only",
                )
            )
    return findings


#: (pattern, human label) - matched case-sensitively except where noted;
#: deliberately narrow (Section 88) to avoid flagging ordinary prose that
#: happens to contain the word "token" or "password" without a
#: credential-shaped value attached.
_CREDENTIAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (  # PLACEHOLDER labels only
    (re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE), "password:"),  # PLACEHOLDER
    (re.compile(r"passwd\s*[:=]\s*\S+", re.IGNORECASE), "passwd:"),  # PLACEHOLDER
    (re.compile(r"ssh_private_key\s*[:=]"), "ssh_private_key"),  # PLACEHOLDER
    (re.compile(r"BEGIN OPENSSH PRIVATE KEY"), "BEGIN OPENSSH PRIVATE KEY"),  # PLACEHOLDER
    (re.compile(r"BEGIN RSA PRIVATE KEY"), "BEGIN RSA PRIVATE KEY"),  # PLACEHOLDER
    (re.compile(r"API_KEY\s*[:=]\s*\S+"), "API_KEY="),  # PLACEHOLDER
    (re.compile(r"\bTOKEN\s*=\s*\S+"), "TOKEN="),  # PLACEHOLDER
)

#: A line containing one of these is treated as documentation *naming*
#: the pattern (like this module's own docstring, or a security doc
#: listing forbidden markers) rather than an actual embedded credential.
_ALLOWLIST_MARKERS = ("EXAMPLE", "PLACEHOLDER", "forbidden", "never contain")


@dataclass(frozen=True)
class CredentialFinding:
    path: str
    pattern: str
    line_number: int


def scan_text_for_credentials(text: str, source_path: str = "<text>") -> list[CredentialFinding]:
    findings: list[CredentialFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if any(marker in line for marker in _ALLOWLIST_MARKERS):
            continue
        for pattern, label in _CREDENTIAL_PATTERNS:
            if pattern.search(line):
                findings.append(
                    CredentialFinding(path=source_path, pattern=label, line_number=line_number)
                )
    return findings


#: File suffixes scanned by :func:`scan_tree_for_credentials` - text
#: formats only, never a binary ISO/wheel.
_SCANNABLE_SUFFIXES = frozenset({".sh", ".py", ".json", ".cfg", ".yaml", ".yml", ".md", ".txt"})


def scan_tree_for_credentials(root: Path) -> list[CredentialFinding]:
    findings: list[CredentialFinding] = []
    if not root.is_dir():
        return findings
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNABLE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text_for_credentials(text, source_path=str(path)))
    return findings
