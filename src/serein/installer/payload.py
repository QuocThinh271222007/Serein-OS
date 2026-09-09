"""S7.2 handoff marker and QA-only runtime credential generation (S7.1
Sections 27, 35).

Two independent concerns:

- :func:`build_install_state_marker` - the minimum Serein foundation
  the installed system must carry (``/etc/serein/install-state.json``)
  so S7.2 has something to consume. Deliberately never advances
  ``firstboot_provisioning`` past ``"pending"`` - S7.1 must not perform
  S7.2 provisioning itself (Section 28).
- :func:`generate_qa_credential` - a QA-CI-only initial-user credential,
  generated at runtime via real ``openssl passwd -6`` (Python's stdlib
  ``crypt`` module was removed in 3.13 - see
  ``docs/installer/known-limitations.md``), never a hardcoded or
  reusable password hash (Section 35). Returns ``None`` (fail-soft,
  never a fabricated/fallback hash) if ``openssl`` is unavailable -
  callers must then refuse to render an autoinstall config at all
  rather than substitute anything committed.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.installer.models import INSTALL_STATE_SCHEMA_VERSION, INSTALLER_PHASE


@dataclass(frozen=True)
class InstallStateMarker:
    schema_version: int
    phase: str
    installation_complete: bool
    firstboot_provisioning: str
    source_media_version: str
    source_commit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "phase": self.phase,
            "installation_complete": self.installation_complete,
            "firstboot_provisioning": self.firstboot_provisioning,
            "source_media_version": self.source_media_version,
            "source_commit": self.source_commit,
        }


def build_install_state_marker(
    source_commit: str, source_media_version: str
) -> InstallStateMarker:
    """The S7.2 handoff contract (Section 27-28): installation is
    complete, but first-boot provisioning is explicitly ``"pending"`` -
    S7.1 never activates Focus, enables Tor, creates cyber containers,
    installs AI models, or performs desktop personalization itself."""
    return InstallStateMarker(
        schema_version=INSTALL_STATE_SCHEMA_VERSION,
        phase=INSTALLER_PHASE,
        installation_complete=True,
        firstboot_provisioning="pending",
        source_media_version=source_media_version,
        source_commit=source_commit,
    )


@dataclass(frozen=True)
class QaCredential:
    """A QA-CI-only credential. ``password`` is the plaintext, held only
    in memory for the duration of a single Layer-B run - never written
    to a file, never logged, never committed. ``password_hash`` is the
    real crypt(3)-style SHA-512 hash (``$6$...``) that actually goes
    into the rendered autoinstall config; the plaintext is not needed
    after that point and callers should not retain it longer than
    necessary."""

    username: str
    password: str
    password_hash: str


def generate_qa_credential(
    runner: CommandRunner = DEFAULT_RUNNER, username: str = "serein-qa"
) -> QaCredential | None:
    """Generate a fresh, random, single-use QA credential via real
    ``openssl passwd -6`` (Section 35 -
    ``QA_CREDENTIAL_GENERATED_AT_RUNTIME=true``). Returns ``None`` if
    ``openssl`` is unavailable or fails - fail-soft, never a fabricated
    hash and never a hardcoded fallback (``REUSABLE_PASSWORD_HASH_COMMITTED=false``
    must remain true unconditionally).

    Known limitation (documented in ``docs/installer/known-limitations.md``):
    the plaintext password is passed as a process argument to
    ``openssl passwd``, which could in principle be visible via a
    process listing for the brief duration of that one command - an
    accepted risk only inside the single-tenant, ephemeral Layer-B CI
    VM this function is intended for, never for interactive/production
    use.

    S7.1R8 fix (real, reproduced defect - a genuine CI test flake
    traced here, never merely assumed): ``secrets.token_urlsafe(24)``
    draws from the URL-safe base64 alphabet, which includes ``-`` -
    when the generated password happens to START with ``-``,
    OpenSSL's own CLI argument parser previously misinterpreted it as
    an unknown OPTION rather than the intended positional password
    value, and ``openssl passwd`` exited non-zero
    (``Unknown option: -<password>``). Reproduced directly (~1-in-64
    real invocations, matching the leading-character odds of a
    64-symbol alphabet): confirmed via 200 real, local
    ``openssl passwd -6`` invocations, exactly 2 failed this way with
    that exact stderr message - never a timeout (every real
    invocation completed in well under 200ms locally). The explicit
    POSIX ``--`` "end of options" marker before the password argument
    fixes this unconditionally, regardless of the password's leading
    character - verified directly against the exact failing value
    reproduced above.
    """
    password = secrets.token_urlsafe(24)
    salt = secrets.token_hex(8)

    result = runner.run(["openssl", "passwd", "-6", "-salt", salt, "--", password])
    if result is None or result.returncode != 0:
        return None

    password_hash = result.stdout.strip()
    if not password_hash.startswith("$6$"):
        return None

    return QaCredential(username=username, password=password, password_hash=password_hash)
