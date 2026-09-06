"""Packet capture tool and privilege detection.

Tool presence (``wireshark``/``tshark``/``dumpcap``) and capture
*privilege* are two genuinely separate questions (Section 8/9) — this
module never infers the latter from the former. Privilege evidence
comes exclusively from ``dumpcap -D`` (list capture-capable
interfaces): Wireshark's own documentation names this as the safe,
read-only way to check whether the current user can capture, since it
enumerates interfaces without capturing a single packet.

``dumpcap -D`` returning a nonzero exit status does **not** by itself
prove a permission problem (S5R corrective) — it can also fail for
reasons entirely unrelated to capture rights (a transient runtime
error, an unsupported flag on an unexpected `dumpcap` build, etc.), and
even a *successful* (returncode 0) run can legitimately list zero
interfaces on a machine with no capturable NICs, which is not evidence
of "permitted" either. The tri-state result is therefore:

- ``True``  — only when ``dumpcap -D`` succeeds **and** its output
  contains at least one interface-list line (the stable ``N. name``
  format) — real, non-empty evidence the current user can enumerate a
  capture-capable interface.
- ``False`` — only when the command's output actually contains
  permission-denial language ("permission denied", "you do not have
  permission", "operation not permitted", "insufficient privileges",
  or the raw ``EPERM``/``EACCES`` errno names) — matched case-
  insensitively across several known phrasings, never a single
  hardcoded string, and never inferred from a bare nonzero exit code.
- ``None`` — everything else: dumpcap not installed, the command
  couldn't run at all, it succeeded but listed no interfaces, or it
  failed for a reason that doesn't look permission-related. Unknown is
  preferable to false certainty in every one of these cases.

Serein never runs an actual capture, never lists real interface
names/identifiers in status output (Section 53 — only the boolean
permission outcome is kept; the interface-list parser below only ever
checks for *presence* of at least one line, never captures or returns
the matched text), never changes ``dumpcap``'s file capabilities, and
never adds the user to a capture-privileged group (Section 7).
"""

from __future__ import annotations

import re

from serein.cyber.models import PacketCaptureStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool

# dumpcap -D's stable human-readable output is a numbered list, one
# interface per line: "1. eth0", "2. lo (Loopback)", etc. This pattern
# only detects *presence* of at least one such line - the matched text
# itself is never retained or returned (Section 53 privacy invariant).
_INTERFACE_LINE_RE = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)

# Known phrasings dumpcap/libpcap use for an actual permission/access
# failure - matched as a substring set, not a single exact string,
# since real dumpcap builds vary in exact wording.
_PERMISSION_DENIAL_MARKERS = (
    "permission denied",
    "you don't have permission",
    "you do not have permission",
    "operation not permitted",
    "insufficient privileges",
    "eperm",
    "eacces",
)


def _has_nonempty_interface_list(text: str) -> bool:
    return _INTERFACE_LINE_RE.search(text) is not None


def _looks_like_permission_denial(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _PERMISSION_DENIAL_MARKERS)


def _check_capture_permission(
    dumpcap_installed: bool, runner: CommandRunner
) -> tuple[bool | None, str]:
    if not dumpcap_installed:
        return None, "dumpcap not installed; nothing to evaluate."
    result = runner.run(["dumpcap", "-D"], timeout=5.0)
    if result is None:
        return None, "dumpcap -D could not be run; capture permission unknown."
    text = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0:
        if _has_nonempty_interface_list(text):
            return (
                True,
                "dumpcap -D succeeded and listed at least one capture-capable "
                "interface (without capturing any packet) - capture is "
                "permitted for the current user.",
            )
        return (
            None,
            "dumpcap -D succeeded but listed no interfaces - capture "
            "permission for this user is unknown.",
        )
    if _looks_like_permission_denial(text):
        return (
            False,
            "dumpcap -D reported a permission-related failure - capture is "
            "not permitted for the current user without a privilege change "
            "Serein does not perform automatically.",
        )
    return (
        None,
        "dumpcap -D failed for a reason that does not look permission-"
        "related - capture permission for this user is unknown.",
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
