# Development Package Strategy

## Source classification

Every tool `packages.py` declares carries an explicit `source_type`:

| Source type | Meaning | Examples |
|---|---|---|
| `ubuntu-repository` | A real apt package in Ubuntu's own archive | git, cmake, podman |
| `official-upstream-repository` | The vendor's own package repo (not Ubuntu's, not a PPA) | GitHub CLI's own apt repo (documented, not used by default — see git-strategy.md) |
| `official-upstream-binary` | A vendor-provided installer/prebuilt binary, user-level | uv, pnpm, Zed |
| `language-bootstrap-tool` | A tool whose job is installing other runtimes | rustup, fnm |
| `optional` | Not part of the default plan; documented only | Docker, micromamba, tmux |

No arbitrary PPA is used anywhere. No tool's default plan action pipes
`curl` straight into a shell — every official-upstream-binary tool's
installer is *documented* (URL + what it does), never executed by S3.

## Verified against the real Ubuntu 26.04 archive

Every `ubuntu-repository` package name below was checked with
`apt-cache policy` and a full `apt-get install --simulate` in a
disposable, isolated Ubuntu 26.04 WSL2 instance — see
`docs/validation/s3/package-validation.md`. Two real corrections came
out of that check:

- **`p7zip-full` no longer exists** — renamed `7zip` in current Ubuntu.
- **`fd-find` and `bat` install their binaries as `fdfind` and
  `batcat`**, not `fd`/`bat` — a long-standing Debian naming collision
  with unrelated packages. Detection code accounts for this.

## Default package groups

| Group | Packages | Why |
|---|---|---|
| `base` | curl, wget, gnupg, openssh-client, unzip, zip, 7zip, rsync, tree | Baseline CLI tools nearly every workflow needs. |
| `git` | git, git-lfs, gh | Version control + large-file support + GitHub CLI. |
| `cpp` | build-essential, gcc, g++, clang, cmake, ninja-build, pkg-config, gdb, lldb, strace | Both compiler families, both debuggers, both build-system generators. |
| `go` | golang-go | Verified 1.26.0 — see go-strategy.md. |
| `containers` | podman, distrobox | See container-strategy.md / ADR-0011. |
| `cli-productivity` | ripgrep, fd-find, fzf, jq, bat, eza, btop, zoxide | Compact, each with a clear, common development use. |

**Deliberately excluded from cli-productivity:** `yq`. Ubuntu's `yq`
package is the Python (kislyuk) wrapper around `jq`, not the far more
commonly referenced Go-based `mikefarah/yq` — shipping the wrong tool
under a familiar name would be worse than omitting it; not included
pending a deliberate, documented choice between the two.

**Optional, not installed by default:** `ccache`, `valgrind`, `ltrace`
(specialized debugging tools with real but narrower use cases), `tmux`
(a shell-workflow preference orthogonal to a Zed-centric editor
workflow), `docker` (see ADR-0011), `micromamba` (see python-strategy.md).

## Non-APT tools (never executed by S3)

`uv`, `fnm`, `pnpm`, `rustup`, `zed` — each has no (or no adequate)
Ubuntu package and is installed via its own official, user-level
installer. See each tool's own strategy doc for the exact source and
reasoning; Section 86/87's "download → verify → execute" model is the
target for a future Apply step, not something S3 implements.

## Package-set quality

The full corrected default set was verified to install cleanly (`0 to
remove`, no conflicts) and does not implicitly pull in any kitchen-sink
application — see docs/validation/s3/package-validation.md.
