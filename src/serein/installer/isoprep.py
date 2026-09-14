"""Prepare a QA-autoinstall Serein ISO variant for S7.1 Layer-B
installer validation (Section 3, 25).

Takes the ALREADY-BUILT S7.0 QA ISO (``serein-alpha-*-qa.iso``,
produced by ``python -m serein.distribution build``) and extracts it
fresh into a NEW, installer-owned scratch tree - never touching
``distribution``'s own ``build/work/extracted`` (S7.1 owns its own
artifacts; "prefer configuration and adapters, never reopening S7.0
internals" - Section 3-4). Writes a rendered ``autoinstall.yaml`` at
the extracted tree's root - the conventional location Subiquity
auto-detects on the install medium (see
``docs/distribution/upstream-installer-research.md``) - then rebuilds
into ``serein-alpha-*-qa-install.iso`` reusing the SAME real boot flags
the original QA ISO's own El Torito report describes, so this variant
boots identically except for the added autoinstall config.

Reuses ``serein.distribution.iso``'s pure command builders (never
imports or calls anything from ``serein.distribution.build`` - this
module has its own, independent, narrowly-scoped pipeline).

S7.1R3 fix (Run #3, RUN_ID=34224122883): placing ``autoinstall.yaml``
at the tree root was NEVER sufficient on its own - the QA ISO's
already-baked-in boot entry (``serein.distribution.qa_boot``'s
``QA_ENTRY_TITLE``, "Serein Alpha (qa-serial-boot-smoke)") is
explicitly documented and coded to NEVER carry the ``autoinstall``
kernel parameter, since that entry exists only to prove S7.0's own ISO
boots (a read-only smoke test - ``qa_boot.py``'s own module docstring:
"never add autoinstall and never touch any disk target"). Real Run #3
evidence proved the booted kernel command line was exactly
``BOOT_IMAGE=/casper/vmlinuz console=ttyS0,115200n8 --- splash`` - no
``autoinstall`` token anywhere - so Subiquity never entered unattended
mode at all; the medium booted into a completely normal interactive
live desktop session (matching every other observed Run #3 symptom:
the full stock snap set loading, the target disk never being touched,
and the run eventually exhausting its 1800s timeout).
``prepare_qa_install_iso`` now further patches ITS OWN independent
copy of the extracted tree to add the ``autoinstall`` kernel
parameter to that one specific boot entry - never touching
``serein.distribution.qa_boot`` itself, whose "never autoinstall"
contract must remain intact for S7.0's own boot-smoke use case.
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from serein.distribution.iso import (
    build_extract_command,
    build_rebuild_command,
    build_report_command,
    parse_el_torito_report,
)
from serein.distribution.models import VOLUME_ID
from serein.distribution.pathsafety import PathSafetyError, resolve_within
from serein.distribution.qa_boot import QA_ENTRY_TITLE, QaBootError, discover_grub_config
from serein.installer.renderer import (
    QA_EVIDENCE_WATCHER_ISO_FILENAME,
    build_qa_evidence_watcher_script,
)

# S7.1R16 Objective A: the QA-only guest evidence watcher is embedded
# as a real file at the ISO's own root (the SAME mechanism
# ``autoinstall.yaml`` already uses - never the squashfs, which this
# project has no tooling to modify, per docs/installer/
# known-limitations.md's own S7.1R12 architectural note). This filename
# is defined in ``serein.installer.renderer`` (re-exported here for
# callers that only need the ISO-prep-facing name), never redeclared as
# an independent string literal that could silently drift apart.
#
# S7.1R17/R18 tried starting the watcher's own short-lived launcher via
# a `systemd.run=` kernel command-line token (plus
# `systemd.run_success_action=none`/`systemd.run_failure_action=none`
# to stop it tearing the live environment down on completion). Real
# Run #19 evidence (RUN_ID=34832918752) proved that even with both of
# those R18 fixes in place, `systemd.run=`'s mere presence on the QA
# boot entry still prevents the rest of the normal live-session boot
# graph (snapd, Subiquity, everything) from ever starting - see
# ``serein.installer.renderer.build_qa_evidence_launcher_script``'s own
# docstring for the full observed-evidence/inferred-mechanism
# breakdown. S7.1R19 retires ALL THREE kernel tokens
# (``systemd.run=``/``systemd.run_success_action=``/
# ``systemd.run_failure_action=``) from this module entirely - this
# module no longer patches the QA boot entry's kernel command line to
# launch the watcher at all. The launcher is now instead embedded into
# the rendered ``autoinstall.yaml`` itself, as a base64-encoded
# ``early-commands`` directive (Subiquity's own normal execution point,
# which structurally cannot disrupt the live session's own boot graph
# the way a kernel-level generator token can) - see
# ``serein.installer.renderer.render_autoinstall_yaml``/
# ``_qa_evidence_launcher_early_command`` for that wiring. This module
# now only ever writes the WATCHER file itself (unchanged) - the
# launcher script is no longer written as a separate file at all.


class IsoPrepError(RuntimeError):
    """Raised for any QA-install-ISO preparation failure - fail closed,
    never ship a half-prepared variant."""


class AutoinstallBootError(RuntimeError):
    """Raised when the QA-install ISO's boot configuration cannot be
    safely patched to trigger unattended autoinstall - fail closed.
    Mirrors ``serein.distribution.qa_boot.QaBootError``'s own
    "never guess, never ship a silently-broken boot entry" discipline,
    but is a distinct, S7.1-owned error type - never reuses or
    subclasses the S7.0 one, keeping the two subsystems'
    error-handling independent (Section 3-4)."""


_QA_MENUENTRY_RE = re.compile(r'menuentry\s+["\']([^"\']*)["\'][^{]*\{', re.IGNORECASE)
_LINUX_LINE_RE = re.compile(r"^(\s*linux(?:efi)?\s+)(\S+)(.*)$", re.IGNORECASE | re.MULTILINE)


@contextmanager
def _temporarily_owner_writable(path: Path) -> Iterator[None]:
    """Ensure ``path`` has its owner-write bit set for the duration of
    this context, then restore its exact original mode afterward - even
    if the body raises. An independently-owned, S7.1-scoped copy of the
    same tiny pattern ``serein.distribution.qa_boot`` uses for the
    identical real reason (S7.0RM5 Corrective A: a real Layer-B run hit
    ``PermissionError`` writing a non-owner-writable extracted file) -
    never imports the private helper across module boundaries; this
    operates only on isoprep's own extracted tree, never
    ``build/work/extracted``."""
    original_mode = stat.S_IMODE(path.stat().st_mode)
    try:
        if not original_mode & stat.S_IWUSR:
            path.chmod(original_mode | stat.S_IWUSR)
        yield
    finally:
        path.chmod(original_mode)


def _add_kernel_token_to_qa_entry(
    grub_cfg_text: str, token: str, entry_title: str = QA_ENTRY_TITLE
) -> str:
    """Add one bare kernel parameter ``token`` to the named menuentry's
    ``linux``/``linuxefi`` line. Inserted before a ``---`` init-arg
    separator if present (mirrors ``qa_boot._add_serial_console``'s own
    placement rule) - never after it, since anything after ``---`` is
    passed to the init process, not the kernel, on a casper live boot
    line.

    Idempotent: a no-op if ``token`` is already present, so re-running
    preparation twice (or adding several tokens in sequence) never
    duplicates anything. Raises :class:`AutoinstallBootError` if the
    named entry, or a ``linux``/``linuxefi`` line inside it, cannot be
    found - never silently ships a QA-install ISO whose intended kernel
    parameter failed to attach. The generalized core behind both
    :func:`_enable_autoinstall_on_qa_entry` (Run #3's real, evidence-
    proven fix) and :func:`_enable_journald_console_forwarding_on_qa_entry`
    (S7.1R5 Objective C).
    """
    matches = list(_QA_MENUENTRY_RE.finditer(grub_cfg_text))
    for index, match in enumerate(matches):
        if match.group(1) != entry_title:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(grub_cfg_text)
        body = grub_cfg_text[start:end]

        linux_match = _LINUX_LINE_RE.search(body)
        if not linux_match:
            raise AutoinstallBootError(
                f"menuentry {entry_title!r} has no linux/linuxefi line to patch - "
                "AUTOINSTALL_BOOT=BLOCKED"
            )
        directive, kernel_path, args = linux_match.groups()
        if re.search(rf"(?<!\S){re.escape(token)}(?!\S)", args):
            return grub_cfg_text  # already present - idempotent no-op

        if "---" in args:
            before, sep, after = args.partition("---")
            new_args = f"{before.rstrip()} {token} {sep}{after}"
        else:
            new_args = f"{args.rstrip()} {token}"
        new_line = f"{directive}{kernel_path}{new_args}"
        new_body = body[: linux_match.start()] + new_line + body[linux_match.end() :]
        return grub_cfg_text[:start] + new_body + grub_cfg_text[end:]

    raise AutoinstallBootError(
        f"no menuentry titled {entry_title!r} found in the extracted QA-install tree - "
        "AUTOINSTALL_BOOT=BLOCKED (S7.1R3)"
    )


def _enable_autoinstall_on_qa_entry(
    grub_cfg_text: str, entry_title: str = QA_ENTRY_TITLE
) -> str:
    """Add the bare ``autoinstall`` kernel parameter to the named
    menuentry - the real, evidence-proven Run #3 fix (see this module's
    own docstring for the full causal chain)."""
    return _add_kernel_token_to_qa_entry(grub_cfg_text, "autoinstall", entry_title)


def _enable_journald_console_forwarding_on_qa_entry(
    grub_cfg_text: str, entry_title: str = QA_ENTRY_TITLE
) -> str:
    """S7.1R5 Objective C: add ``systemd.journald.forward_to_console=1``
    to the named menuentry.

    Run #4/#5 both proved the guest reaches real userspace with
    Subiquity-related snap apparmor profiles loading (per the
    `snap.ubuntu-desktop-bootstrap.subiquity-server`/`.curtin` lines
    real serial evidence showed), but the serial console alone never
    showed Subiquity/curtin/cloud-init's OWN log output - only kernel/
    systemd boot messages. Since `ubuntu-desktop-bootstrap`'s installer
    services run as ordinary systemd-managed snap services, their
    stdout/stderr is captured by the systemd journal by default, not
    necessarily echoed to any console. This standard, well-documented
    systemd kernel parameter forwards ALL journal entries to the
    active console in real time - a single, low-risk kernel parameter
    addition (the smallest robust mechanism per Section 8 of the
    S7.1R5 corrective), never a new guest-side service, mount, or
    transport. This is the SAME evidence-gathering intent as R3's
    `autoinstall` fix - reusing the SAME real, tested mechanism
    (:func:`_add_kernel_token_to_qa_entry`) rather than inventing a new
    one.
    """
    return _add_kernel_token_to_qa_entry(
        grub_cfg_text, "systemd.journald.forward_to_console=1", entry_title
    )


def _enable_systemd_debug_logging_on_qa_entry(
    grub_cfg_text: str, entry_title: str = QA_ENTRY_TITLE
) -> str:
    """S7.1R7 Objective A: add ``systemd.log_level=debug`` to the named
    menuentry.

    Real Run #7 evidence (RUN_ID=34335197624), surfaced entirely via
    R5's journald-forwarding fix above, showed a ~3044s pre-Subiquity
    bootstrap window dominated by real systemd/snapd activity (service
    startup timeouts, restarts, a desktop-security-center hook
    failure/sanity timeout, mass snap service removal/remount, an NTP
    10-minute wait) - but at systemd's default log level, WHY each of
    these transitions occurred (exact dependency-ordering reasoning,
    job-timeout detail) is not necessarily logged. Debug-level systemd
    logging surfaces materially more detail about job/unit state
    transitions and timeout reasoning, still purely a kernel-parameter
    change through the SAME real, already-proven mechanism - never a
    new guest-side service, file, or transport. Not expected to
    increase noise unmanageably since only systemd's own logging
    verbosity changes, not application-level (e.g. snapd's own)
    verbosity.
    """
    return _add_kernel_token_to_qa_entry(grub_cfg_text, "systemd.log_level=debug", entry_title)


def _mask_firmware_notifier_on_qa_entry(
    grub_cfg_text: str, entry_title: str = QA_ENTRY_TITLE
) -> str:
    """S7.1R9 Objective A: add
    ``systemd.mask=snap.firmware-updater.firmware-notifier.service`` to
    the named menuentry.

    Real Run #9 evidence (RUN_ID=34371427617) - the first run to reach
    real Subiquity postinstall/curthooks completion and enter
    unattended-upgrades - showed a pathological restart storm of
    ``snap.firmware-updater.firmware-notifier.service`` starting around
    ~3730.94s and continuing to at least the 599th observed restart,
    each attempt failing with "Sorry, home directories outside of
    /home needs configuration." (a well-known real Ubuntu snapd
    home-dirs confinement message, not anything Serein's own code
    introduces or references - confirmed absent from this repository
    outside this one corrective).

    ``firmware-updater`` is part of Ubuntu's own stock desktop snap
    set (present on the base ISO before Serein ever touches it, per
    this module's own docstring on the extracted tree's provenance),
    and this specific failure mode is a documented live-session/
    installer-environment artifact of snapd's confinement home-dirs
    check, not a defect in the eventually-installed target system
    (the real end user's real ``/home`` is correctly configured on
    the installed system - this notifier's live-session autostart
    entry is the only thing affected).

    Masking is QA-install-boot-session-only, via the SAME
    already-proven, generalized kernel-token mechanism used for R3's
    ``autoinstall``/R5's journald-forwarding/R7's debug-logging
    tokens - ``systemd.mask=<unit>`` is a real, documented systemd
    kernel command-line option (see systemd's own
    ``kernel-command-line(7)``) that masks a unit for THIS BOOT ONLY,
    entirely in-memory - it never writes anything to the ISO's
    persisted unit files, never touches the installed target's
    package set or unit files (which come from ``curtin in-target``/
    the target's own debootstrap seed, not from live-boot kernel
    parameters), and never disables firmware-update functionality on
    the shipped Serein product. This is the narrowest available
    corrective: it suppresses only the one specific pathological
    restart loop, on the QA boot entry only, leaving the production
    boot entry (which never carries any of these QA-only tokens)
    completely untouched.
    """
    return _add_kernel_token_to_qa_entry(
        grub_cfg_text,
        "systemd.mask=snap.firmware-updater.firmware-notifier.service",
        entry_title,
    )


def prepare_qa_install_iso(
    qa_iso_path: Path,
    work_dir: Path,
    output_iso: Path,
    autoinstall_yaml_text: str,
    subprocess_runner: object = subprocess.run,
) -> Path:
    """Extract ``qa_iso_path``, patch its boot entry to actually trigger
    unattended autoinstall (S7.1R3), write ``autoinstall_yaml_text`` at
    the tree root, and rebuild into ``output_iso``. ``subprocess_runner``
    is injectable (must accept the same positional/``check`` signature
    as ``subprocess.run``) so this whole pipeline is unit-testable with
    a fake ``xorriso`` - mirroring
    ``serein.distribution.build.run_build``'s own injection pattern."""
    if not qa_iso_path.is_file():
        raise IsoPrepError(f"{qa_iso_path} does not exist")

    extracted_dir = work_dir / "qa-install-extracted"
    if extracted_dir.exists():
        shutil.rmtree(extracted_dir)
    extracted_dir.mkdir(parents=True)

    extract_result = subprocess_runner(  # type: ignore[operator]
        build_extract_command(qa_iso_path, extracted_dir),
        capture_output=True, text=True, check=False,
    )
    if extract_result.returncode != 0:
        raise IsoPrepError(f"extraction of {qa_iso_path} failed: {extract_result.stderr}")

    report_result = subprocess_runner(  # type: ignore[operator]
        build_report_command(qa_iso_path), capture_output=True, text=True, check=False
    )
    if report_result.returncode != 0:
        raise IsoPrepError(f"el-torito report for {qa_iso_path} failed: {report_result.stderr}")
    boot_flags = parse_el_torito_report(report_result.stdout)

    # S7.1R3: the proven real Run #3 fix - without this, the rebuilt
    # medium boots into a normal interactive live session and never
    # touches the target disk at all (see module docstring).
    try:
        grub_relative = discover_grub_config(extracted_dir)
    except QaBootError as exc:
        raise IsoPrepError(f"cannot enable autoinstall boot: {exc}") from exc
    try:
        grub_path = resolve_within(extracted_dir, grub_relative)
    except PathSafetyError as exc:
        raise IsoPrepError(
            f"cannot enable autoinstall boot: {grub_relative!r} escapes the "
            f"extraction root: {exc}"
        ) from exc
    original_grub_text = grub_path.read_text(encoding="utf-8")
    try:
        patched_grub_text = _enable_autoinstall_on_qa_entry(original_grub_text)
        # S7.1R5 Objective C / S7.1R7 Objective A: both chained onto the
        # same, already-patched text - never a second independent
        # grub.cfg parse/write cycle.
        patched_grub_text = _enable_journald_console_forwarding_on_qa_entry(patched_grub_text)
        patched_grub_text = _enable_systemd_debug_logging_on_qa_entry(patched_grub_text)
        # S7.1R9 Objective A: chained onto the same already-patched
        # text, same discipline as the two lines above.
        patched_grub_text = _mask_firmware_notifier_on_qa_entry(patched_grub_text)
        # S7.1R19 corrective: no further kernel token is added here.
        # R16-R18 added a `systemd.run=` token (plus two exit-action
        # tokens) to start the QA guest-evidence launcher independently
        # of Subiquity - real Run #19 evidence proved that token's mere
        # presence prevents the rest of the normal live-session boot
        # graph from ever starting. The launcher is now instead
        # launched via an `early-commands` autoinstall directive (see
        # `serein.installer.renderer.render_autoinstall_yaml`) - never
        # a kernel command-line patch, so no further GRUB mutation is
        # needed for it.
    except AutoinstallBootError as exc:
        raise IsoPrepError(f"cannot enable autoinstall boot: {exc}") from exc
    with _temporarily_owner_writable(grub_path):
        grub_path.write_text(patched_grub_text, encoding="utf-8")

    autoinstall_path = extracted_dir / "autoinstall.yaml"
    autoinstall_path.write_text(autoinstall_yaml_text, encoding="utf-8")

    # S7.1R16 Objective A: the long-running watcher lives at the
    # extracted tree ROOT - the exact same "outer ISO filesystem, never
    # the squashfs" placement `autoinstall.yaml` already uses, reachable
    # at boot via casper's own early `/cdrom` mount (the same mount
    # point Subiquity itself reads `/cdrom/autoinstall.yaml` from) -
    # `build_rebuild_command`'s own `-r` (Rock Ridge) flag preserves
    # this permission bit into the rebuilt ISO, the same way it already
    # preserves grub.cfg's. S7.1R19: the launcher is no longer written
    # as a separate file here at all - it is base64-embedded directly
    # into the rendered `autoinstall.yaml`'s own early-commands entry
    # (`autoinstall_yaml_text`, already written above), invoked by
    # Subiquity itself, which in turn invokes THIS watcher file via
    # `systemd-run` at its own early-commands execution point.
    watcher_path = extracted_dir / QA_EVIDENCE_WATCHER_ISO_FILENAME
    watcher_path.write_text(build_qa_evidence_watcher_script(), encoding="utf-8")
    watcher_path.chmod(0o755)

    output_iso.parent.mkdir(parents=True, exist_ok=True)
    rebuild_cmd = build_rebuild_command(extracted_dir, boot_flags, output_iso, VOLUME_ID)
    rebuild_result = subprocess_runner(  # type: ignore[operator]
        rebuild_cmd, capture_output=True, text=True, check=False
    )
    if rebuild_result.returncode != 0:
        raise IsoPrepError(f"rebuild of {output_iso} failed: {rebuild_result.stderr}")

    return output_iso
