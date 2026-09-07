"""Private workspace readiness and kill-switch modeling.

``evaluate_workspace_readiness`` is the single canonical private-
workspace verdict (Section 55) - ``capabilities.py``, ``planner.py``,
and ``doctor.py`` all consume this instead of each deriving "is a
workspace usable" independently (the exact class of bug S5R's VM-
readiness corrective fixed, applied here from the start). ``usable`` is
never ``True`` merely because Tor and Tor Browser are both installed
(Section 57) - S6 never creates or configures an actual isolation
boundary (no network namespace, no rootless container, no browser
profile), so ``configured`` stays ``False`` and real usability of a
genuine privacy workspace is never proven yet.

A kill switch is defined only conceptually (Section 23-24/58) - S6
never mutates firewall/network policy, so ``configured``/``usable`` are
constants, not probe results.
"""

from __future__ import annotations

from serein.veil.models import (
    KillSwitchStatus,
    TorBrowserStatus,
    TorStatusInfo,
    VeilWorkspaceReadiness,
)


def evaluate_kill_switch() -> KillSwitchStatus:
    return KillSwitchStatus()


def evaluate_workspace_readiness(
    tor: TorStatusInfo, tor_browser: TorBrowserStatus, environment_is_container: bool
) -> VeilWorkspaceReadiness:
    mechanism = "isolated browser profile + SOCKS5h (Tor Browser preferred)"
    if not environment_is_container:
        mechanism += "; rootless network namespace/container is an additional future candidate"

    if tor.usable is False:
        return VeilWorkspaceReadiness(
            candidate=True, configured=False, usable=False, privacy_level="none",
            mechanism=mechanism,
            reason="Tor client is not usable, so no privacy workspace "
            "mechanism can be considered ready.",
        )
    if tor.usable is None:
        return VeilWorkspaceReadiness(
            candidate=True, configured=False, usable=None, privacy_level="none",
            mechanism=mechanism,
            reason="Tor client usability is unknown, so workspace readiness "
            "cannot be evaluated either.",
        )
    # tor.usable is True. Tor Browser's presence does not raise the
    # privacy level either - see the reason text below.
    return VeilWorkspaceReadiness(
        candidate=True, configured=False, usable=None, privacy_level="tor_application",
        mechanism=mechanism,
        reason="Tor client is usable" + (
            " and torbrowser-launcher is present" if tor_browser.launcher_installed else ""
        ) + ", but no explicit workspace isolation mechanism (namespace/"
        "container/isolated browser profile) has actually been created - "
        "S6 only detects/plans, never provisions one (Section 5/78-79), so "
        "real usability of an isolated privacy workspace stays unknown. "
        "'isolated_workspace'/'whonix' privacy levels require an actually-"
        "configured boundary this phase never builds.",
    )
