"""Fastfetch terminal-identity integration (Phase-7-completion Section
16-17).

**Honesty note (Section 82/29):** Fastfetch is not installed anywhere
in this development/CI environment - `build_fastfetch_config`'s output
has only ever been reviewed by hand against Fastfetch's own documented
JSON config schema, never run through a real `fastfetch` binary. This
mirrors this project's own established precedent for
`distribution/systemd/serein-firstboot.service`
(`docs/firstboot/known-limitations.md`: "reviewed by hand... never run
through real systemd-analyze verify"). Real runtime-rendering proof is
future work, tracked in `docs/branding/known-limitations.md`.

Design constraints actually honored here (verifiable independent of a
real fastfetch binary):

- the mandatory ASCII/Unicode logo fallback (Section 17) - no
  terminal-image protocol is ever required for core output;
- Focus/Mode read REAL state where it exists
  (`serein.focus.runtime.read_focus_runtime_state`) - Section 16 never
  fabricates a value; "balanced" (no committed transition yet) always
  displays as "Default", exactly the initial state Section 16 itself
  describes as acceptable;
- Mode has no real resource-mode contract to read yet (Section 21 -
  "Do NOT implement the full resource allocator in this phase") - a
  fixed, honestly-labelled "Balanced" placeholder, never a fabricated
  live value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from serein.focus.runtime import read_focus_runtime_state
from serein.hardware._util import DEFAULT_ROOT

#: Section 16: "If no committed active focus exists: Focus Default" -
#: the display mapping from a real FOCUS_TARGETS value to what a human
#: reads in the terminal.
_FOCUS_DISPLAY_NAMES: dict[str, str] = {
    "balanced": "Default",
    "dev": "Development",
    "ai": "AI",
    "cyber": "Cybersecurity",
    "private": "Private",
}

#: Section 21: Performance/Balanced/Efficiency/Isolated resource modes
#: are a future contract - no resource-mode state exists to read yet,
#: so this is a fixed, honest placeholder, never a fabricated value.
MODE_DISPLAY_LABEL = "Balanced"

#: Repo-relative path to the mandatory ASCII/Unicode logo fallback
#: (Section 12/17) - the same file `serein.branding.manifest` already
#: registers as the shipped `terminal-mark-ascii` asset.
TERMINAL_MARK_REPO_PATH = "branding/terminal/serein-mark.txt"

#: Where the config below expects that file to already live on an
#: installed system - a real, first-boot-owned path (`etc/serein` is
#: already one of firstboot's own `_CORE_DIRECTORIES`), but the actual
#: write is NOT yet wired anywhere (tracked as
#: SEREIN-FASTFETCH-LOGO-STAGING-PENDING in
#: docs/branding/known-limitations.md) - a small, near-term follow-up
#: analogous to SEREIN-DESKTOP-STAGING-PENDING, deliberately not
#: expanded into this same change.
FASTFETCH_LOGO_SYSTEM_PATH = "/etc/serein/branding/terminal-mark.txt"

#: The command a fastfetch "command"-type module actually shells out
#: to for the Focus line (Section 16) - kept as one named constant so
#: the generated config and the CLI entrypoint below can never drift
#: apart into two different invocations.
FOCUS_LABEL_COMMAND = "python3 -m serein.branding focus-label"


def focus_display_label(root: Path = DEFAULT_ROOT) -> str:
    """The exact text fastfetch's Focus command module prints - always
    the real persisted `serein.focus.runtime` state, never fabricated."""
    state = read_focus_runtime_state(root)
    return _FOCUS_DISPLAY_NAMES.get(state.active_focus, state.active_focus.title())


def build_fastfetch_config(logo_system_path: str = FASTFETCH_LOGO_SYSTEM_PATH) -> dict[str, Any]:
    """The Fastfetch jsonc config content. See this module's own
    docstring for the "reviewed by hand, never run" honesty note."""
    return {
        "$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json",
        "logo": {
            "type": "file",
            "source": logo_system_path,
            "padding": {"top": 1, "left": 2},
        },
        "display": {"separator": "  "},
        "modules": [
            {"type": "custom", "format": "S E R E I N"},
            {"type": "custom", "format": "quiet velocity"},
            "break",
            {"type": "os", "key": "OS", "format": "Serein"},
            {"type": "custom", "key": "Base", "format": "Ubuntu"},
            {"type": "kernel", "key": "Kernel"},
            {"type": "shell", "key": "Shell"},
            {"type": "wm", "key": "Session"},
            {"type": "cpu", "key": "CPU"},
            {"type": "gpu", "key": "GPU"},
            {"type": "memory", "key": "Memory"},
            "break",
            {"type": "command", "key": "Focus", "text": FOCUS_LABEL_COMMAND},
            {"type": "custom", "key": "Mode", "format": MODE_DISPLAY_LABEL},
        ],
    }
