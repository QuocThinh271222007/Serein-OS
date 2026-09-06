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
