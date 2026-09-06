"""Packet capture tool and privilege detection.

Tool presence (``wireshark``/``tshark``/``dumpcap``) and capture
*privilege* are two genuinely separate questions (Section 8/9) — this
module never infers the latter from the former. Privilege evidence
comes exclusively from ``dumpcap -D`` (list capture-capable
interfaces): Wireshark's own documentation names this as the safe,
read-only way to check whether the current user can capture, since it
enumerates interfaces without capturing a single packet. If the
current user lacks capture rights, ``dumpcap -D`` fails with a
permission error; if they have rights (via ``cap_net_raw``/
``cap_net_admin`` file capabilities on the binary, or ``wireshark``
group membership), it succeeds and lists interfaces.

Serein never runs an actual capture, never lists real interface
names/identifiers in status output (Section 53 — only the boolean
permission outcome is kept), never changes ``dumpcap``'s file
capabilities, and never adds the user to a capture-privileged group
(Section 7).
"""

from __future__ import annotations

from serein.cyber.models import PacketCaptureStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def _check_capture_permission(
    dumpcap_installed: bool, runner: CommandRunner
) -> tuple[bool | None, str]:
    if not dumpcap_installed:
        return None, "dumpcap not installed; nothing to evaluate."
    result = runner.run(["dumpcap", "-D"], timeout=5.0)
    if result is None:
        return None, "dumpcap -D could not be run; capture permission unknown."
    if result.returncode == 0:
        return (
            True,
            "dumpcap -D succeeded (lists capture-capable interfaces without "
            "capturing any packet) - capture is permitted for the current user.",
        )
    return (
        False,
        "dumpcap -D failed (permission denied) - capture is not permitted "
        "for the current user without a privilege change Serein does not "
        "perform automatically.",
    )


def detect_capture_status(runner: CommandRunner = DEFAULT_RUNNER) -> PacketCaptureStatus:
    dumpcap = probe_tool("dumpcap", "dumpcap", version_args=("-v",), runner=runner)
    permitted, reason = _check_capture_permission(dumpcap.installed, runner)
    return PacketCaptureStatus(
        wireshark=probe_tool("wireshark", "wireshark", version_args=("-v",), runner=runner),
        tshark=probe_tool("tshark", "tshark", version_args=("-v",), runner=runner),
        dumpcap=dumpcap,
        capture_permitted=permitted,
        capture_permission_reason=reason,
    )
