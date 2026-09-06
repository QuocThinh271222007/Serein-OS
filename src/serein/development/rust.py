"""Rust toolchain detection.

``rustup``-managed and distro-packaged ``rustc``/``cargo`` both resolve
to the same ``--version`` probe here — distinguishing which one actually
provided the active toolchain is not attempted by S3 (would require
resolving ``$PATH`` order or `rustup which`, more precision than the
conflict policy needs: presence of ``rustup`` itself is what the planner
gates on). See docs/development/rust-strategy.md.
"""

from __future__ import annotations

from serein.development.models import RustStatusInfo
from serein.development.runner import DEFAULT_RUNNER, CommandRunner
from serein.development.toolchains import probe_tool


def detect_rust_status(runner: CommandRunner = DEFAULT_RUNNER) -> RustStatusInfo:
    return RustStatusInfo(
        rustup=probe_tool("rustup", "rustup", runner=runner),
        rustc=probe_tool("rustc", "rustc", runner=runner),
        cargo=probe_tool("cargo", "cargo", runner=runner),
    )
