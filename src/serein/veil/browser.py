"""Tor Browser and ordinary-browser detection.

Tor Browser is never equated with an ordinary browser routed through a
SOCKS proxy (Section 17/105/54) - Tor Browser bundles anti-fingerprinting
and privacy hardening (uniform window size, disabled/patched WebRTC,
letterboxing, first-party isolation, NoScript defaults) that plain
Firefox-plus-proxy does not have. Serein's policy is "privacy-sensitive
browsing -> Tor Browser", not "teach Serein to recreate Tor Browser via
Firefox settings" (Section 17).

Detection never scans the user's home directory for an unpacked Tor
Browser bundle (Section 29's "no filesystem-wide search" principle,
generalized) - the only detected mechanism is ``torbrowser-launcher``,
verified present in Ubuntu's universe repository, which downloads and
signature-verifies the official Tor Project release. See
docs/veil/tor-browser.md.
"""

from __future__ import annotations

from serein.development.dpkg import apt_package_installed
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool
from serein.veil.models import OrdinaryBrowserStatus, TorBrowserStatus


def detect_tor_browser_status(runner: CommandRunner = DEFAULT_RUNNER) -> TorBrowserStatus:
    launcher = probe_tool(
        "torbrowser-launcher", "torbrowser-launcher", version_args=("--version",), runner=runner
    )
    installed = launcher.installed or apt_package_installed(
        "torbrowser-launcher", runner=runner
    )
    if not installed:
        return TorBrowserStatus(
            launcher=launcher, launcher_installed=False, usable=None,
            reason="torbrowser-launcher is not installed; nothing to evaluate. "
            "The official Tor Browser tarball (torproject.org) is an "
            "equally valid, user-managed alternative Serein never "
            "downloads on its own behalf (Section 18-19).",
        )
    return TorBrowserStatus(
        launcher=launcher, launcher_installed=True, usable=None,
        reason="torbrowser-launcher is installed - this only confirms the "
        "official-release download/verification helper is present, not "
        "that the actual Tor Browser bundle has been downloaded, "
        "verified, or run; Serein never triggers that first run "
        "automatically, so usable stays unknown.",
    )


def detect_ordinary_browser_status(runner: CommandRunner = DEFAULT_RUNNER) -> OrdinaryBrowserStatus:
    return OrdinaryBrowserStatus(
        firefox=probe_tool("firefox", "firefox", version_args=("--version",), runner=runner),
        chromium=probe_tool(
            "chromium", "chromium-browser", version_args=("--version",), runner=runner
        ),
    )
