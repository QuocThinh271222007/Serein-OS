"""Reverse-engineering baseline detection.

``gdb``/``strace`` are reused directly from S3's
``serein.development.cpp.detect_cpp_status()`` (Section 59) rather
than re-probed — S3 already owns that exact detection evidence for the
C/C++ debugging toolchain, and gdb/strace are the same binaries for
either purpose. Detection is presence-only: no binary is disassembled,
scanned, or indexed (Section 68 — no filesystem-wide executable scan).
"""

from __future__ import annotations

from serein.cyber.models import ReverseEngineeringStatus
from serein.development.cpp import detect_cpp_status
from serein.development.dpkg import apt_package_installed
from serein.development.models import ToolStatus
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_reverse_status(runner: CommandRunner = DEFAULT_RUNNER) -> ReverseEngineeringStatus:
    cpp = detect_cpp_status(runner=runner)
    # binutils has no single canonical launcher binary; objdump is a
    # representative member, and dpkg package state is checked too
    # (same dual-evidence pattern S4's nvidia.py uses for CUDA Toolkit)
    # since a user may have only one of the two tools/binaries present.
    objdump = probe_tool("objdump", "objdump", runner=runner)
    binutils_installed = objdump.installed or apt_package_installed("binutils", runner=runner)
    binutils = ToolStatus(id="binutils", installed=binutils_installed, version=objdump.version)

    return ReverseEngineeringStatus(
        file=probe_tool("file", "file", version_args=("--version",), runner=runner),
        binutils=binutils,
        gdb=cpp.gdb,
        strace=cpp.strace,
        radare2=probe_tool("radare2", "r2", version_args=("-v",), runner=runner),
        ghidra=probe_tool("ghidra", "ghidraRun", runner=runner),
    )
