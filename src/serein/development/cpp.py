"""C/C++ toolchain and debugger detection.

All eight tools are plain Ubuntu-repository packages (verified against
the real Ubuntu 26.04 archive — see docs/validation/s3/
package-validation.md); Serein neither forces gcc-over-clang nor the
reverse (docs/development/cpp-strategy.md).
"""

from __future__ import annotations

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
    )
