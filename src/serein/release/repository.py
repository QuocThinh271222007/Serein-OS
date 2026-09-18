"""Signed Serein APT repository tooling (Phase-7-completion Section
43/49/50).

Developer-side tooling for generating a local, signed APT repository
from a directory of `.deb` packages - never a custom, insecure ad-hoc
repository format. Uses real `dpkg-scanpackages`/`gpg`, the same tools
any real Debian-family repository uses. Supports a local/file
repository for testing without needing a production domain (Section
49) - a real production domain/signing-key ceremony is explicitly
deferred (Section 93).

Never the deprecated global `apt-key` pattern (Section 43): the
generated client-side `.sources` file uses the modern DEB822 format
with an explicit `Signed-By:` pointing at an exported keyring file,
never `apt-key add`. `sign_release_detached`/`sign_release_inline`
never touch the caller's real `~/.gnupg` - every call requires an
explicit, isolated `gnupghome` (Section 50 - tests use disposable
ephemeral keys, never a real signing key, and this module makes that
the only way to call it, never an accidental default).
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path


class RepositoryError(RuntimeError):
    """Raised when a real `dpkg-scanpackages`/`gpg` invocation fails."""


def scan_packages(repo_dir: Path) -> str:
    """Runs `dpkg-scanpackages` over `repo_dir`, returns the `Packages`
    index content. `repo_dir` must contain only trusted `.deb` files
    this caller already built/vetted - never an arbitrary,
    untrusted directory."""
    result = subprocess.run(
        ["dpkg-scanpackages", "--multiversion", ".", "/dev/null"],
        cwd=repo_dir, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RepositoryError(f"dpkg-scanpackages failed: {result.stderr}")
    return result.stdout


def render_release_file(
    repo_dir: Path,
    packages_relative_path: str,
    suite: str,
    codename: str,
    architectures: str = "amd64",
) -> str:
    """A hand-written `Release` file (Origin/Label/Suite/Codename/
    Architectures/Components/Date + a real SHA256 of the indexed
    `Packages` file) - `apt-ftparchive release` can also produce this;
    this explicit version keeps every field reviewable rather than
    trusting `apt-ftparchive`'s own config-file indirection."""
    packages_path = repo_dir / packages_relative_path
    data = packages_path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)
    date = time.strftime("%a, %d %b %Y %H:%M:%S UTC", time.gmtime())

    lines = [
        "Origin: Serein OS",
        "Label: Serein",
        f"Suite: {suite}",
        f"Codename: {codename}",
        f"Architectures: {architectures}",
        "Components: main",
        f"Date: {date}",
        "SHA256:",
        f" {sha256} {size} {packages_relative_path}",
    ]
    return "\n".join(lines) + "\n"


def sign_release_detached(
    repo_dir: Path, release_filename: str, signing_key_fingerprint: str, gnupghome: Path
) -> Path:
    """`gpg --detach-sign --armor` -> `<release_filename>.gpg`."""
    release_path = repo_dir / release_filename
    sig_path = repo_dir / f"{release_filename}.gpg"
    result = subprocess.run(
        [
            "gpg", "--homedir", str(gnupghome), "--batch", "--yes",
            "--local-user", signing_key_fingerprint,
            "--detach-sign", "--armor", "-o", str(sig_path), str(release_path),
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RepositoryError(f"gpg detach-sign failed: {result.stderr}")
    return sig_path


def sign_release_inline(
    repo_dir: Path, release_filename: str, signing_key_fingerprint: str, gnupghome: Path
) -> Path:
    """`gpg --clearsign` -> `InRelease` (the modern, single-file
    signed release format most current APT clients prefer)."""
    release_path = repo_dir / release_filename
    inrelease_path = repo_dir / "InRelease"
    result = subprocess.run(
        [
            "gpg", "--homedir", str(gnupghome), "--batch", "--yes",
            "--local-user", signing_key_fingerprint,
            "--clearsign", "-o", str(inrelease_path), str(release_path),
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RepositoryError(f"gpg clearsign failed: {result.stderr}")
    return inrelease_path


def verify_release_signature(signed_path: Path, gnupghome: Path) -> bool:
    """`gpg --verify` against a clearsigned/detached-signed file -
    True only if the signature is cryptographically valid against a
    key already present in `gnupghome`. Never installs or trusts a key
    itself - the caller decides what keys `gnupghome` contains."""
    result = subprocess.run(
        ["gpg", "--homedir", str(gnupghome), "--batch", "--verify", str(signed_path)],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def render_apt_sources(base_url: str, suite: str, keyring_path: str) -> str:
    """The modern DEB822 `.sources` format (never a legacy one-line
    `.list` file, never `apt-key`) - `Signed-By:` points at an
    exported keyring file, never the global apt-key keyring (Section
    43)."""
    lines = [
        "Types: deb",
        f"URIs: {base_url}",
        f"Suites: {suite}",
        "Components: main",
        f"Signed-By: {keyring_path}",
    ]
    return "\n".join(lines) + "\n"
