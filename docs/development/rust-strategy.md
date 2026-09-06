# Rust Strategy

- **`rustup`** remains the sole official Rust installer upstream —
  unchanged, verified during S3 research. Official installer:
  `rustup.rs` (documented, never executed by S3), installing
  `rustc`/`cargo`/`rustup` into `~/.cargo`/`~/.rustup`.
- **Base components**: the `stable` toolchain, `cargo`, `rustfmt`, and
  `clippy` — no nightly toolchain by default.
- **Optional**: `rust-src`, `llvm-tools` — only added if a concrete,
  justified need arises (not part of the default plan).

## Conflict policy (Section 62/63 of the S3 brief)

- **`rustup` already present → `NOOP`.** Serein never reinstalls it.
- **Only a distro-packaged `rustc`/`cargo` exists (no `rustup`) →
  `APPLY` rustup**, with an explicit note that rustup installs
  additively into `~/.cargo` and does not remove or modify the existing
  distro packages. This reflects Serein's policy choice (an
  upstream-managed, easily-updated toolchain) rather than silently
  accepting a potentially stale distro version — but the existing
  installation is never touched.
- **Neither exists → `APPLY` rustup**, installing the stable toolchain
  only.

## Cache locations (documented, not moved)

Cargo's registry/build cache lives under `~/.cargo/registry` and
`target/` directories per-project by Cargo's own default. Serein does
not relocate them; if disk usage optimization is ever warranted, that
is S8's job (measure first, per Integrate → Measure → Replace).
