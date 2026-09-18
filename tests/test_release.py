"""Tests for the Serein release/version/update-infrastructure
subsystem (Phase-7-completion Section 42-53).

Signing tests use real, disposable, ephemeral GPG keys generated fresh
per test into an isolated ``GNUPGHOME`` under ``tmp_path`` - never the
real host's keyring, never a committed key (Section 50 - "Tests may
create ephemeral disposable signing keys. Never commit private key
material."). Skips (never fails) when ``gpg``/``dpkg-scanpackages`` is
unavailable, matching this project's established Windows/CI-
portability discipline.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from serein.release.channels import CHANNELS, DEFAULT_CHANNEL, is_valid_channel
from serein.release.migration import Migration, run_migrations
from serein.release.repository import (
    RepositoryError,
    render_apt_sources,
    render_release_file,
    scan_packages,
    sign_release_detached,
    sign_release_inline,
    verify_release_signature,
)
from serein.release.version import build_release_version


class TestChannels:
    def test_default_is_stable(self) -> None:
        assert DEFAULT_CHANNEL == "stable"

    def test_dev_is_never_default(self) -> None:
        assert DEFAULT_CHANNEL != "dev"

    def test_all_three_channels_present(self) -> None:
        assert set(CHANNELS) == {"stable", "beta", "dev"}

    def test_is_valid_channel(self) -> None:
        assert is_valid_channel("stable") is True
        assert is_valid_channel("not-a-real-channel") is False


class TestVersion:
    def test_reuses_the_real_package_version_never_a_second_literal(self) -> None:
        import serein

        version = build_release_version()
        assert version.serein_version == serein.__version__

    def test_default_channel_is_stable(self) -> None:
        version = build_release_version()
        assert version.channel == "stable"

    def test_carries_source_commit_when_given(self) -> None:
        version = build_release_version(source_commit="a" * 40)
        assert version.source_commit == "a" * 40

    def test_source_commit_none_when_not_given(self) -> None:
        version = build_release_version()
        assert version.source_commit is None


class TestMigrationFramework:
    def test_no_applicable_migrations_is_a_noop(self, tmp_path: Path) -> None:
        results = run_migrations(tmp_path, current_version=5, migrations=())
        assert results == []

    def test_applies_in_ascending_order(self, tmp_path: Path) -> None:
        order: list[int] = []
        migrations = (
            Migration(
                "0002", 2, 3, "second",
                apply=lambda root: order.append(2), verify=lambda root: True,
            ),
            Migration(
                "0001", 1, 2, "first",
                apply=lambda root: order.append(1), verify=lambda root: True,
            ),
        )
        run_migrations(tmp_path, current_version=1, migrations=migrations)
        assert order == [1, 2]

    def test_skips_migrations_already_behind_current_version(self, tmp_path: Path) -> None:
        applied: list[str] = []
        migrations = (
            Migration(
                "0001", 1, 2, "old",
                apply=lambda root: applied.append("0001"), verify=lambda root: True,
            ),
        )
        run_migrations(tmp_path, current_version=5, migrations=migrations)
        assert applied == []

    def test_real_apply_and_verify_against_a_fixture_file(self, tmp_path: Path) -> None:
        marker = tmp_path / "marker.txt"

        def apply(root: Path) -> None:
            (root / "marker.txt").write_text("migrated\n", encoding="utf-8")

        def verify(root: Path) -> bool:
            return (root / "marker.txt").read_text(encoding="utf-8") == "migrated\n"

        migration = Migration("0001", 1, 2, "write marker", apply=apply, verify=verify)
        results = run_migrations(tmp_path, current_version=1, migrations=(migration,))
        assert results[0].applied is True
        assert results[0].verified is True
        assert marker.is_file()

    def test_failed_verification_stops_the_sequence(self, tmp_path: Path) -> None:
        order: list[int] = []
        migrations = (
            Migration(
                "0001", 1, 2, "fails verify",
                apply=lambda root: order.append(1), verify=lambda root: False,
            ),
            Migration(
                "0002", 2, 3, "never reached",
                apply=lambda root: order.append(2), verify=lambda root: True,
            ),
        )
        results = run_migrations(tmp_path, current_version=1, migrations=migrations)
        assert order == [1]
        assert len(results) == 1
        assert results[0].verified is False

    def test_rollback_runs_on_failed_verification_when_reversible(self, tmp_path: Path) -> None:
        rolled_back: list[bool] = []
        migration = Migration(
            "0001", 1, 2, "reversible but fails",
            apply=lambda root: None,
            verify=lambda root: False,
            rollback=lambda root: rolled_back.append(True),
        )
        results = run_migrations(tmp_path, current_version=1, migrations=(migration,))
        assert rolled_back == [True]
        assert results[0].rolled_back is True

    def test_no_rollback_claimed_when_not_reversible(self, tmp_path: Path) -> None:
        migration = Migration(
            "0001", 1, 2, "irreversible",
            apply=lambda root: None, verify=lambda root: False, rollback=None,
        )
        results = run_migrations(tmp_path, current_version=1, migrations=(migration,))
        assert results[0].rolled_back is False

    def test_apply_exception_is_caught_and_reported(self, tmp_path: Path) -> None:
        def broken_apply(root: Path) -> None:
            raise RuntimeError("boom")

        migration = Migration(
            "0001", 1, 2, "broken", apply=broken_apply, verify=lambda root: True
        )
        results = run_migrations(tmp_path, current_version=1, migrations=(migration,))
        assert results[0].applied is False
        assert "boom" in results[0].detail


class TestAptSources:
    def test_deb822_format_never_a_legacy_one_liner(self) -> None:
        text = render_apt_sources(
            "file:///srv/serein-repo", "stable", "/usr/share/keyrings/serein-archive-keyring.gpg"
        )
        assert "Types: deb" in text
        assert "Signed-By:" in text
        # A legacy one-line .list entry starts with "deb " - the DEB822
        # format never does.
        assert not text.lstrip().startswith("deb ")

    def test_never_references_apt_key(self) -> None:
        text = render_apt_sources("file:///srv/serein-repo", "stable", "/some/keyring.gpg")
        assert "apt-key" not in text.lower()


def _gpg() -> str:
    gpg = shutil.which("gpg")
    if gpg is None:
        pytest.skip("gpg not available")
    return gpg


def _dpkg_scanpackages() -> None:
    if shutil.which("dpkg-scanpackages") is None:
        pytest.skip("dpkg-scanpackages not available")


def _generate_ephemeral_key(gnupghome: Path, uid: str) -> str:
    """Real, disposable ED25519 key generation into an isolated
    GNUPGHOME - never the real host keyring, never committed anywhere
    (Section 50)."""
    gnupghome.mkdir(mode=0o700, exist_ok=True)
    result = subprocess.run(
        [
            _gpg(), "--homedir", str(gnupghome), "--batch", "--passphrase", "",
            "--quick-generate-key", uid, "ed25519", "sign", "never",
        ],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr

    list_result = subprocess.run(
        [_gpg(), "--homedir", str(gnupghome), "--batch", "--list-secret-keys", "--with-colons"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    for line in list_result.stdout.splitlines():
        if line.startswith("fpr:"):
            return line.split(":")[9]
    raise AssertionError(f"no fingerprint found in: {list_result.stdout}")


class TestPackagesIndex:
    def test_empty_directory_produces_empty_index(self, tmp_path: Path) -> None:
        _dpkg_scanpackages()
        output = scan_packages(tmp_path)
        assert output.strip() == ""


class TestReleaseFile:
    def test_sha256_and_size_are_real(self, tmp_path: Path) -> None:
        packages = tmp_path / "Packages"
        packages.write_bytes(b"Package: serein-core\nVersion: 0.1.0\n\n")

        text = render_release_file(tmp_path, "Packages", "stable", "resolute")
        import hashlib

        expected_sha = hashlib.sha256(packages.read_bytes()).hexdigest()
        assert expected_sha in text
        assert str(packages.stat().st_size) in text
        assert "Origin: Serein OS" in text
        assert "Suite: stable" in text


class TestSignedRelease:
    def test_valid_signature_accepted(self, tmp_path: Path) -> None:
        gnupghome = tmp_path / "gnupg"
        fingerprint = _generate_ephemeral_key(gnupghome, "Serein Test <test@example.invalid>")

        release = tmp_path / "Release"
        release.write_text("Origin: Serein OS\nSuite: stable\n", encoding="utf-8")

        inrelease = sign_release_inline(tmp_path, "Release", fingerprint, gnupghome)
        assert inrelease.is_file()
        assert verify_release_signature(inrelease, gnupghome) is True

    def test_wrong_key_rejected(self, tmp_path: Path) -> None:
        signer_home = tmp_path / "signer"
        verifier_home = tmp_path / "verifier"
        fingerprint = _generate_ephemeral_key(signer_home, "Signer <signer@example.invalid>")
        _generate_ephemeral_key(verifier_home, "Verifier <verifier@example.invalid>")

        release = tmp_path / "Release"
        release.write_text("Origin: Serein OS\nSuite: stable\n", encoding="utf-8")
        inrelease = sign_release_inline(tmp_path, "Release", fingerprint, signer_home)

        # The verifier's own keyring never imported the signer's public
        # key - verification against it must fail.
        assert verify_release_signature(inrelease, verifier_home) is False

    def test_unsigned_release_is_rejected(self, tmp_path: Path) -> None:
        gnupghome = tmp_path / "gnupg"
        _generate_ephemeral_key(gnupghome, "Serein Test <test@example.invalid>")
        plain_release = tmp_path / "Release"
        plain_release.write_text("Origin: Serein OS\nSuite: stable\n", encoding="utf-8")
        assert verify_release_signature(plain_release, gnupghome) is False

    def test_tampered_signed_content_rejected(self, tmp_path: Path) -> None:
        gnupghome = tmp_path / "gnupg"
        fingerprint = _generate_ephemeral_key(gnupghome, "Serein Test <test@example.invalid>")

        release = tmp_path / "Release"
        release.write_text("Origin: Serein OS\nSuite: stable\n", encoding="utf-8")
        inrelease = sign_release_inline(tmp_path, "Release", fingerprint, gnupghome)

        # Real clearsigned files fail cryptographic verification if any
        # byte of the signed content changes.
        tampered = inrelease.read_text(encoding="utf-8").replace("stable", "TAMPERED")
        inrelease.write_text(tampered, encoding="utf-8")
        assert verify_release_signature(inrelease, gnupghome) is False

    def test_detached_signature_round_trip(self, tmp_path: Path) -> None:
        gnupghome = tmp_path / "gnupg"
        fingerprint = _generate_ephemeral_key(gnupghome, "Serein Test <test@example.invalid>")

        release = tmp_path / "Release"
        release.write_text("Origin: Serein OS\nSuite: stable\n", encoding="utf-8")
        sig_path = sign_release_detached(tmp_path, "Release", fingerprint, gnupghome)
        assert sig_path.is_file()
        # gpg --verify on a detached signature needs the signed file
        # alongside it (same directory, default naming) - verify
        # against the .gpg file directly.
        result = subprocess.run(
            [
                _gpg(), "--homedir", str(gnupghome), "--batch", "--verify",
                str(sig_path), str(release),
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_signing_with_unknown_fingerprint_raises(self, tmp_path: Path) -> None:
        _gpg()
        gnupghome = tmp_path / "gnupg"
        gnupghome.mkdir(mode=0o700)
        release = tmp_path / "Release"
        release.write_text("Origin: Serein OS\n", encoding="utf-8")
        with pytest.raises(RepositoryError):
            sign_release_inline(tmp_path, "Release", "0" * 40, gnupghome)
