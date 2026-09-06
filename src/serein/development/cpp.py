"""C/C++ toolchain and debugger detection.

All ten tools are plain Ubuntu-repository packages (verified against
the real Ubuntu 26.04 archive — see docs/validation/s3/
package-validation.md); Serein neither forces gcc-over-clang nor the
reverse (docs/development/cpp-strategy.md). ``build-essential`` is a
metapackage with no binary of its own, so its presence is checked via
real dpkg package state (``serein.development.dpkg``), never inferred
from ``gcc`` (or any other binary) being on ``PATH`` — the S3R
corrective (a binary can exist without the metapackage being the thing
that installed it, and vice versa is not the concern, but the reverse
inference is the actual bug that was fixed here).
"""

from __future__ import annotations

from serein.development.dpkg import apt_package_installed
from serein.development.models import CppStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_cpp_status(runner: CommandRunner = DEFAULT_RUNNER) -> CppStatusInfo:
    return CppStatusInfo(
        gcc=probe_tool("gcc", "gcc", runner=runner),
        gpp=probe_tool("g++", "g++", runner=runner),
        clang=probe_tool("clang", "clang", runner=runner),
        cmake=probe_tool("cmake", "cmake", runner=runner),
        ninja=probe_tool("ninja", "ninja", runner=runner),
        gdb=probe_tool("gdb", "gdb", runner=runner),
        lldb=probe_tool("lldb", "lldb", runner=runner),
        pkg_config=probe_tool("pkg-config", "pkg-config", runner=runner),
        strace=probe_tool("strace", "strace", runner=runner),
        build_essential_installed=apt_package_installed("build-essential", runner=runner),
    )


def cpp_installed_map(status: CppStatusInfo) -> dict[str, bool]:
    """Apt-package-name -> installed, matching ``packages.CPP_TOOLS``'
    package ids exactly. Single source of truth shared by the planner
    (which reports a missing subset) and capabilities (which reports
    an all-or-nothing summary) so the two can never diverge about
    which packages count as "the C/C++ toolchain"."""
    return {
        "build-essential": status.build_essential_installed,
        "gcc": status.gcc.installed,
        "g++": status.gpp.installed,
        "clang": status.clang.installed,
        "cmake": status.cmake.installed,
        "ninja-build": status.ninja.installed,
        "pkg-config": status.pkg_config.installed,
        "gdb": status.gdb.installed,
        "lldb": status.lldb.installed,
        "strace": status.strace.installed,
    }


def cpp_toolchain_fully_installed(status: CppStatusInfo) -> bool:
    """True only when every required C/C++ package is present. Used by
    ``capabilities.py`` for ``cpp_toolchain.installed`` - kept in sync
    with the planner's missing-subset computation via
    ``cpp_installed_map`` so capability/plan can never disagree (the
    S2RM lesson, applied here to avoid an S3-native recurrence)."""
    return all(cpp_installed_map(status).values())
