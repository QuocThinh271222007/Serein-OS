# C/C++ Toolchain Strategy

## Base toolchain (all real Ubuntu 26.04 packages, verified)

```
build-essential   gcc/g++/make/libc headers metapackage
gcc, g++          GNU compiler family
clang             LLVM compiler family
cmake, ninja-build  build-system generator + fast build backend
pkg-config        library compile-flag discovery
gdb               GNU debugger
lldb              LLVM debugger
strace            syscall tracer
```

Both compiler families and both debuggers are installed side by side —
**Serein never changes `update-alternatives` for `cc`/`c++`, and never
globally prefers GCC over Clang or the reverse.** A project chooses its
compiler explicitly (`CC=clang`, a CMake toolchain file, etc.).

## Package-state detection (S3R corrective)

`build-essential` is a metapackage — it installs `gcc`/`g++`/`make`/libc
headers as dependencies but owns no binary of its own. Its presence is
therefore **never** inferred from `gcc` (or any other binary) being on
`PATH` — that would be wrong in both directions (a hand-installed
`gcc` without the metapackage, or a metapackage whose `gcc` was later
removed independently). Instead, `serein.development.dpkg
.apt_package_installed()` makes one read-only, injectable
`dpkg-query -W -f='${Status}' build-essential` call and checks for
`install ok installed` in its output — the same `CommandRunner`
abstraction every other detector uses, never a raw `subprocess` call
and never a package-manager mutation. `CppStatusInfo
.build_essential_installed` carries this fact as a plain boolean (not a
`ToolStatus`, since there is no version or binary to report), and
`cpp.cpp_installed_map()`/`cpp_toolchain_fully_installed()` are the one
shared place both the planner (missing-subset reporting) and
`capabilities.py` (all-or-nothing `cpp_toolchain.installed`) read from,
so the two can never disagree about what counts as "the C/C++
toolchain" — mirroring the S2RM capability/planner-consistency lesson.

## Optional (not installed by default)

```
ccache      compiler cache - a build-speed convenience, not required to compile
valgrind    memory/thread error detector - heavier, specialized use case
ltrace      library-call tracer - niche, ptrace-based tool
```

Each was evaluated individually (Section 24 of the S3 brief) rather than
bundled reflexively; none is excluded for being unimportant, only for
not being universal enough to justify a default install.

## Debugging posture

`gdb`/`lldb`/`strace` are baseline. **Serein never changes Ubuntu's
`ptrace` security defaults** (`kernel.yama.ptrace_scope`) to make
debugging more convenient — that would weaken a real security boundary
for a development-convenience reason the S3 brief explicitly forbids
(Section 27).

## Build systems

Baseline: Make (via build-essential), CMake, Ninja, pkg-config. Meson
was evaluated and not included by default — no concrete Serein-target
workflow currently requires it beyond what CMake/Ninja already covers;
revisit if a measured need appears.
