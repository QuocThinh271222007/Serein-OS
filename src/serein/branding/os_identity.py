"""Serein OS identity - ``/etc/os-release``, ``/etc/issue``,
``/etc/issue.net`` content generation (Phase-7-completion Section 19).

Generated and written at first-boot time
(``serein.firstboot.steps.step_initialize_directories``), never baked
into the squashfs (this project's own established "never modify
squashfs" discipline - see e.g.
``build_qa_evidence_watcher_script``'s own docstring) and never via
curtin late-commands (that mechanism currently only fires on the
QA-only autoinstall path, not a real interactive install - see
``serein.installer.renderer.render_autoinstall_yaml``'s own
``qa_mode`` requirement). First boot is the one point every install
path (QA and, eventually, real interactive) unconditionally reaches.

Serein remains technically accurate as Ubuntu-based (Section 19) -
this module never claims independence from the real upstream base.
``VERSION_ID``/``VERSION_CODENAME``/``UBUNTU_CODENAME`` reuse the same
pinned values ``desktop.models.TARGET_UBUNTU_VERSION`` and
``distribution/base-image.json``'s own ``codename`` field already
carry - never a second, independently-maintained copy of either
(Section 36 - "no duplicate source of truth").
"""

from __future__ import annotations

from serein.desktop.models import TARGET_UBUNTU_VERSION

SEREIN_ID = "serein"
SEREIN_NAME = "Serein"
SEREIN_PRETTY_NAME = "Serein OS"
SEREIN_ID_LIKE = "ubuntu"
SEREIN_HOME_URL = "https://github.com/QuocThinh271222007/Serein-OS"
SEREIN_SUPPORT_URL = "https://github.com/QuocThinh271222007/Serein-OS/issues"
SEREIN_BUG_REPORT_URL = "https://github.com/QuocThinh271222007/Serein-OS/issues"

#: Must stay in sync with distribution/base-image.json's own
#: "codename" field - never re-read from that file at first-boot time
#: (an installed system has no repo checkout to read it from), so a
#: future base-image change must update this constant too, exactly the
#: same manual-sync discipline TARGET_UBUNTU_VERSION already uses.
UPSTREAM_CODENAME = "resolute"


def render_os_release() -> str:
    """Freedesktop.org os-release spec content - see
    https://www.freedesktop.org/software/systemd/man/os-release.html.
    Read back by ``serein.hardware.os_release.read_os_release``, whose
    ``is_ubuntu`` now honors ``ID_LIKE`` as well as a literal
    ``ID=ubuntu`` for exactly this reason."""
    codename_title = UPSTREAM_CODENAME.capitalize()
    lines = [
        f'NAME="{SEREIN_NAME}"',
        f'PRETTY_NAME="{SEREIN_PRETTY_NAME}"',
        f"ID={SEREIN_ID}",
        f"ID_LIKE={SEREIN_ID_LIKE}",
        f'VERSION="{TARGET_UBUNTU_VERSION} (built on Ubuntu {TARGET_UBUNTU_VERSION} '
        f'\\"{codename_title}\\")"',
        f'VERSION_ID="{TARGET_UBUNTU_VERSION}"',
        f"VERSION_CODENAME={UPSTREAM_CODENAME}",
        f"UBUNTU_CODENAME={UPSTREAM_CODENAME}",
        f'HOME_URL="{SEREIN_HOME_URL}"',
        f'SUPPORT_URL="{SEREIN_SUPPORT_URL}"',
        f'BUG_REPORT_URL="{SEREIN_BUG_REPORT_URL}"',
    ]
    return "\n".join(lines) + "\n"


def render_issue() -> str:
    """``/etc/issue`` - shown on a local TTY before login. ``\\n``/``\\l``
    are real ``getty`` escape sequences (hostname/tty name), never
    literal text - preserved verbatim, matching every stock
    distribution's own ``/etc/issue`` convention."""
    return f"{SEREIN_PRETTY_NAME} \\n \\l\n\n"


def render_issue_net() -> str:
    """``/etc/issue.net`` - shown before an SSH/telnet login prompt.
    No ``getty`` escape sequences are honored over a network protocol,
    so this is deliberately plain text only."""
    return f"{SEREIN_PRETTY_NAME}\n"
