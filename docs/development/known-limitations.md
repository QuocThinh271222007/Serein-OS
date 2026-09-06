# Known Limitations (S3)

Explicit per the same "don't overstate what's validated" discipline
every prior phase established.

## No production Apply engine

`serein dev plan` is entirely read-only. No `serein dev apply` command
exists, by deliberate design (Section 12 of the S3 brief) — actual
installation execution is deferred to a later phase integrated with the
global S0 installer lifecycle.

## No full installer / supply-chain verification

Section 86/87's "download → verify → execute a controlled artifact"
model for official-upstream-binary tools (uv, fnm, pnpm, rustup, Zed) is
documented as the target design, not implemented — S3 never downloads
or executes any installer script. No checksum/signature-verification
infrastructure exists yet.

## Live validation was package-only (Tier B), not full-workstation

A disposable, isolated Ubuntu 26.04 WSL2 instance (same methodology as
S1R/S2R/S2RM) validated real `apt-cache policy`/`apt-get --simulate`/
real installs for every Ubuntu-repository package this phase declares —
see `docs/validation/s3/package-validation.md`. This is **not** proof
that:

- Any official-upstream-binary installer (uv, fnm, pnpm, rustup, Zed)
  actually works end-to-end — none were executed, per policy (Section
  94: "Do not install user-level Node/Rust/uv/Zed on the owner's host,"
  extended here to also mean not on any host during S3 authoring, to
  avoid conflating "documented" with "proven").
- Zed's GUI actually runs in any environment (WSL, container, or bare
  metal) — only binary-presence detection is implemented.
- Distrobox's actual container-creation behavior — only its own
  `--version` was checked.

## Tool detection accuracy depends on the host's real PATH/binaries

This repository was developed on a Windows host. Development-tool
detection was exercised against **real, already-installed cross-platform
tools present on that host** (Git for Windows, a Python install, Node,
Zed) rather than fixtures — deliberately, since these detectors call
real commands rather than reading fixture files the way S0-S2's sysfs
probes did (see docs/development/architecture.md's "Command safety"
section). One genuine, informative artifact surfaced during this: Git
for Windows ships its own `strace.exe` (an MSYS2 compatibility shim,
unrelated to Linux's `strace`) that satisfied the `strace` detection
probe — correct, honest behavior for what was actually asked ("does a
binary named `strace` respond to `--version`"), but a reminder that
cross-platform binary-name collisions are a real, not hypothetical,
category of detection risk. Test coverage uses fake `CommandRunner`
instances specifically to keep unit tests independent of whatever
happens to be on any given host's PATH.

## GitHub CLI version-freshness trade-off is real and unresolved

Ubuntu's own `gh` package (chosen as the default, see
docs/development/git-strategy.md) is materially behind GitHub's own
apt repository. This is a deliberate, documented trade-off (avoiding a
third-party apt source by default) — not an oversight, but also not
free of a real cost for users who want `gh`'s newest features.

## No live GPU/container-toolkit validation

ADR-0011's Docker-vs-Podman NVIDIA Container Toolkit maturity claim is
based on external research (see the S3 research summary), not a live
test in this environment — no GPU was available to validate either
engine's GPU-passthrough behavior. This is explicitly S4's problem to
resolve with real hardware.

## `serein dev status`/`doctor`/`plan` on this development host

Every command was run and verified to complete without a traceback on
this Windows host, correctly reporting "missing" for every Linux-only
tool (podman, distrobox, golang-go's Linux binary, etc.) — see the S3
completion report for the exact recorded output.
