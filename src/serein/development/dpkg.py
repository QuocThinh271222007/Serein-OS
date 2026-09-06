"""Read-only APT/dpkg package-installation-state probe.

Distinct from ``toolchains.probe_tool``: a binary's presence on
``PATH`` does not prove a given apt package — especially a metapackage
like ``build-essential``, which owns no binary of its own — is
installed. This module answers "does dpkg's own database say this
package is installed" via a single, injectable, read-only
``dpkg-query`` call. It never mutates anything and never infers
package state from a sibling binary's presence (the S3R corrective:
``gcc`` existing does not prove ``build-essential`` is installed).
"""

from __future__ import annotations

from serein.development.runner import DEFAULT_RUNNER, CommandRunner


def apt_package_installed(package: str, runner: CommandRunner = DEFAULT_RUNNER) -> bool:
    """True only if dpkg reports ``package`` as fully installed. False
    (never raises) if dpkg-query is unavailable — a non-Debian host,
    this repository's own dev machine, or CI — since that is not
    evidence the package is missing, only that dpkg cannot be asked."""
    result = runner.run(["dpkg-query", "-W", "-f=${Status}", package], timeout=3.0)
    if result is None or result.returncode != 0:
        return False
    return "install ok installed" in result.stdout
