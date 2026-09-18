"""``/etc/os-release`` parsing.

Format is defined by the freedesktop.org os-release spec and is stable
across Ubuntu releases; Ubuntu has shipped it unchanged in shape since
16.04. See: https://www.freedesktop.org/software/systemd/man/os-release.html
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import OSInfo


def _parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def read_os_release(root: Path) -> OSInfo:
    text = read_text(root / "etc" / "os-release")
    if text is None:
        return OSInfo()

    values = _parse_os_release(text)
    os_id = values.get("ID")
    id_like = values.get("ID_LIKE", "").split() if values.get("ID_LIKE") else []
    return OSInfo(
        id=os_id,
        id_like=id_like,
        name=values.get("NAME"),
        version_id=values.get("VERSION_ID"),
        pretty_name=values.get("PRETTY_NAME"),
        # A real Serein install sets ID=serein/ID_LIKE=ubuntu (Section 19
        # of the Phase-7-completion brief - Serein remains technically
        # accurate as Ubuntu-based) - "Ubuntu-compatible" must keep
        # meaning that on an actual Serein system, never only ID=ubuntu
        # literally.
        is_ubuntu=(os_id == "ubuntu" or "ubuntu" in id_like),
    )
