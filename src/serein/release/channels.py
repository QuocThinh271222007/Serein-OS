"""Update channel model (Phase-7-completion Section 44).

One canonical configured state per system - never a value re-derived
differently by different consumers."""

from __future__ import annotations

CHANNELS: tuple[str, ...] = ("stable", "beta", "dev")

#: Section 44: "Default public installation: stable... Do not make dev
#: channel default."
DEFAULT_CHANNEL = "stable"


def is_valid_channel(channel: str) -> bool:
    return channel in CHANNELS
