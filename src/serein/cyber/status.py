"""``serein cyber status``: a read-only cybersecurity-workspace summary.

Safe to run anywhere (Windows dev host, Ubuntu, WSL, CI, a container) —
every field degrades to an honest "unavailable"/"unknown" rather than
raising. Reuses the existing ``cyber`` profile entry from the profile
registry (S2) rather than introducing a second profile concept
(Section 61 — one profile file, hardware and software layers both
described in it, exactly like S3/S4 extended ``dev``/``ai``). Never
lists real capture interface names, MAC addresses, SSIDs, or any other
private network identifier (Section 23/51/53/54).
"""

from __future__ import annotations

from pathlib import Path

from serein.cyber.capture import detect_capture_status
from serein.cyber.models import CyberStatusReport
from serein.cyber.network import detect_network_status
from serein.cyber.reverse import detect_reverse_status
from serein.cyber.toolbox import detect_host_hygiene, detect_toolbox_status
from serein.cyber.virtualization import detect_vm_status
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.hardware._util import DEFAULT_ROOT
from serein.profiles.registry import list_profiles


def build_cyber_status(
    root: Path = DEFAULT_ROOT, runner: CommandRunner = DEFAULT_RUNNER
) -> CyberStatusReport:
    profiles = {p.id: p for p in list_profiles()}
    cyber_profile = profiles.get("cyber")

    return CyberStatusReport(
        schema_version=1,
        profile_id="cyber",
        profile_status=cyber_profile.status if cyber_profile else "declared",
        network=detect_network_status(runner=runner),
        capture=detect_capture_status(runner=runner),
        reverse=detect_reverse_status(runner=runner),
        containers=detect_toolbox_status(runner=runner),
        vm=detect_vm_status(runner=runner, root=root),
        host_hygiene=detect_host_hygiene(runner=runner),
    )
