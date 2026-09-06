"""Serein Development's declarative tool manifest — the single source of
truth for what a Serein Development install requests, and where each
tool comes from.

Every package name below was verified against the real Ubuntu 26.04
archive in a disposable, isolated environment (see docs/validation/s3/
package-validation.md) — including two real corrections this manifest
reflects: ``p7zip-full`` no longer exists (renamed ``7zip``), and
``fd-find``/``bat`` install their binaries as ``fdfind``/``batcat`` (a
long-standing Debian naming collision), not ``fd``/``bat``. This module
is plain data: nothing here executes a package manager or an installer
script. See docs/development/package-strategy.md.
"""

from __future__ import annotations

from serein.development.models import ToolDefinition

# --- Ubuntu-repository groups -------------------------------------------

BASE_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition("curl", "curl", "ubuntu-repository", "curl", True, "HTTP client."),
    ToolDefinition("wget", "wget", "ubuntu-repository", "wget", True, "HTTP client."),
    ToolDefinition("gnupg", "GnuPG", "ubuntu-repository", "gnupg", True, "Signature/key tooling."),
    ToolDefinition(
        "openssh-client", "OpenSSH client", "ubuntu-repository", "openssh-client", True,
        "SSH client only - openssh-server is never installed by Serein.",
    ),
    ToolDefinition("unzip", "unzip", "ubuntu-repository", "unzip", True, "Archive extraction."),
    ToolDefinition("zip", "zip", "ubuntu-repository", "zip", True, "Archive creation."),
    ToolDefinition("7zip", "7-Zip", "ubuntu-repository", "7zip", True, "7z archive support."),
    ToolDefinition("rsync", "rsync", "ubuntu-repository", "rsync", True, "File sync."),
    ToolDefinition("tree", "tree", "ubuntu-repository", "tree", True, "Directory listing."),
)

GIT_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition("git", "Git", "ubuntu-repository", "git", True, "Version control."),
    ToolDefinition(
        "git-lfs", "Git LFS", "ubuntu-repository", "git-lfs", True, "Large file storage support.",
    ),
    ToolDefinition(
        "gh", "GitHub CLI", "ubuntu-repository", "gh", True,
        "Ubuntu's own package (older than GitHub's own apt repo, verified - see "
        "docs/development/git-strategy.md); chosen to avoid adding a third-party "
        "apt source by default.",
    ),
)

CPP_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "build-essential", "build-essential", "ubuntu-repository", "build-essential", True,
        "Metapackage: gcc, g++, make, libc headers.",
    ),
    ToolDefinition("gcc", "GCC", "ubuntu-repository", "gcc", True, "C compiler."),
    ToolDefinition("g++", "G++", "ubuntu-repository", "g++", True, "C++ compiler."),
    ToolDefinition("clang", "Clang", "ubuntu-repository", "clang", True, "LLVM C/C++ compiler."),
    ToolDefinition("cmake", "CMake", "ubuntu-repository", "cmake", True, "Build system generator."),
    ToolDefinition(
        "ninja-build", "Ninja", "ubuntu-repository", "ninja-build", True, "Build system.",
    ),
    ToolDefinition(
        "pkg-config", "pkg-config", "ubuntu-repository", "pkg-config", True,
        "Library compile-flag discovery.",
    ),
    ToolDefinition("gdb", "GDB", "ubuntu-repository", "gdb", True, "GNU debugger."),
    ToolDefinition("lldb", "LLDB", "ubuntu-repository", "lldb", True, "LLVM debugger."),
    ToolDefinition("strace", "strace", "ubuntu-repository", "strace", True, "Syscall tracer."),
)

DEBUG_TOOLS_OPTIONAL: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "ccache", "ccache", "ubuntu-repository", "ccache", True,
        "Compiler cache. Optional: a build-speed convenience, not required to compile.",
    ),
    ToolDefinition(
        "valgrind", "Valgrind", "ubuntu-repository", "valgrind", True,
        "Memory/thread error detector. Optional: heavier, specialized use case.",
    ),
    ToolDefinition(
        "ltrace", "ltrace", "ubuntu-repository", "ltrace", True,
        "Library call tracer. Optional: niche, ptrace-based tool.",
    ),
)

CLI_PRODUCTIVITY_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "ripgrep", "ripgrep", "ubuntu-repository", "ripgrep", True, "Fast recursive grep.",
    ),
    ToolDefinition(
        "fd-find", "fd", "ubuntu-repository", "fd-find", True,
        "Fast find. Ubuntu installs the binary as 'fdfind', not 'fd'.",
    ),
    ToolDefinition("fzf", "fzf", "ubuntu-repository", "fzf", True, "Fuzzy finder."),
    ToolDefinition("jq", "jq", "ubuntu-repository", "jq", True, "JSON processor."),
    ToolDefinition(
        "bat", "bat", "ubuntu-repository", "bat", True,
        "Syntax-highlighted cat. Ubuntu installs the binary as 'batcat', not 'bat'.",
    ),
    ToolDefinition("eza", "eza", "ubuntu-repository", "eza", True, "Modern ls replacement."),
    ToolDefinition("btop", "btop", "ubuntu-repository", "btop", True, "Resource monitor."),
    ToolDefinition("zoxide", "zoxide", "ubuntu-repository", "zoxide", True, "Smarter cd."),
)

CLI_PRODUCTIVITY_OPTIONAL: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "tmux", "tmux", "ubuntu-repository", "tmux", True,
        "Terminal multiplexer. Optional: a shell-workflow preference, not required "
        "for a Zed-centric workflow.",
    ),
)

GO_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "golang-go", "Go", "ubuntu-repository", "golang-go", True,
        "Verified 1.26.0 in the Ubuntu 26.04 archive - close enough to upstream's own "
        "release cadence to prefer over a second version-management layer.",
    ),
)

CONTAINER_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "podman", "Podman", "ubuntu-repository", "podman", True,
        "Preferred default container engine: rootless by default.",
    ),
    ToolDefinition(
        "distrobox", "Distrobox", "ubuntu-repository", "distrobox", True,
        "Development sandboxes/tool isolation, pairs with Podman.",
    ),
)

CONTAINER_TOOLS_OPTIONAL: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "docker", "Docker Engine", "optional", None, True,
        "Not installed by default. Docker's own apt repository (not Ubuntu's, not a "
        "PPA) would be required. Documented for future S4 AI-container-ecosystem needs "
        "where Docker's NVIDIA Container Toolkit support is currently more mature than "
        "Podman's - see docs/development/container-strategy.md and ADR-0011.",
    ),
)

# --- Official-upstream-binary / bootstrap-tool groups (never executed) --

PYTHON_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "uv", "uv", "official-upstream-binary", None, False,
        "Astral's official installer script (astral.sh/uv/install.sh) - no Ubuntu "
        "package exists. Installs to the user's home directory only; system Python "
        "is never touched. See docs/development/python-strategy.md.",
    ),
)

PYTHON_TOOLS_OPTIONAL: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "micromamba", "micromamba", "official-upstream-binary", None, False,
        "Optional: only for projects that require the Conda package ecosystem. Not "
        "installed by default - see docs/development/python-strategy.md.",
    ),
)

JAVASCRIPT_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "fnm", "fnm", "language-bootstrap-tool", None, False,
        "Official installer script (fnm.vercel.app/install) - a single-purpose, "
        "actively-maintained Node version manager. See docs/development/"
        "node-strategy.md and ADR-0010 for why fnm over nvm/mise.",
    ),
    ToolDefinition(
        "pnpm", "pnpm", "official-upstream-binary", None, False,
        "pnpm's own standalone installer (get.pnpm.io/install.sh) - not routed "
        "through Corepack, which Node is phasing out (removed in Node 25+).",
    ),
)

RUST_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "rustup", "rustup", "language-bootstrap-tool", None, False,
        "The sole official Rust installer (rustup.rs) - installs rustc/cargo/rustup "
        "into the user's home directory. See docs/development/rust-strategy.md.",
    ),
)

EDITOR_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "zed", "Zed", "official-upstream-binary", None, False,
        "Zed's official installer script (zed.dev/install.sh) - no official Ubuntu "
        "package or APT repo exists. Installs under the user's home directory, no "
        "sudo. See docs/development/editor-strategy.md.",
    ),
)

ALL_GROUPS: tuple[tuple[str, tuple[ToolDefinition, ...]], ...] = (
    ("base", BASE_TOOLS),
    ("git", GIT_TOOLS),
    ("python", PYTHON_TOOLS),
    ("python-optional", PYTHON_TOOLS_OPTIONAL),
    ("javascript", JAVASCRIPT_TOOLS),
    ("rust", RUST_TOOLS),
    ("go", GO_TOOLS),
    ("cpp", CPP_TOOLS),
    ("debug-optional", DEBUG_TOOLS_OPTIONAL),
    ("containers", CONTAINER_TOOLS),
    ("containers-optional", CONTAINER_TOOLS_OPTIONAL),
    ("cli-productivity", CLI_PRODUCTIVITY_TOOLS),
    ("cli-productivity-optional", CLI_PRODUCTIVITY_OPTIONAL),
    ("editor", EDITOR_TOOLS),
)


def all_tools() -> list[ToolDefinition]:
    """Every declared tool across every group, default and optional
    alike - deduplicated by id."""
    seen: set[str] = set()
    result: list[ToolDefinition] = []
    for _group_name, tools in ALL_GROUPS:
        for tool in tools:
            if tool.id not in seen:
                seen.add(tool.id)
                result.append(tool)
    return result


def default_apt_packages() -> list[str]:
    """Every apt package Serein's *default* (non-optional) manifest
    requests, deduplicated and sorted - mirrors
    ``serein.desktop.packages.all_packages()``'s shape."""
    default_group_names = {"base", "git", "python", "javascript", "rust", "go", "cpp", "containers"}
    seen: set[str] = set()
    result: list[str] = []
    for group_name, tools in ALL_GROUPS:
        if group_name not in default_group_names:
            continue
        for tool in tools:
            package = tool.package
            if tool.source_type == "ubuntu-repository" and package and package not in seen:
                seen.add(package)
                result.append(package)
    # cli-productivity is part of the default plan too (small, high-value set).
    for tool in CLI_PRODUCTIVITY_TOOLS:
        if tool.package and tool.package not in seen:
            seen.add(tool.package)
            result.append(tool.package)
    return sorted(result)
