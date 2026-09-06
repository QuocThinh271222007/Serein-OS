# Go Strategy

## Decision: Ubuntu's own package, not a version manager

Verified live against the real Ubuntu 26.04 archive: `golang-go`
installs Go **1.26.0**. Upstream's own release cadence was at 1.27.1 by
the same date — one minor version ahead. Per Section 23 of the S3
brief's own test ("if Ubuntu's package is sufficiently current, prefer
it"), one minor version of lag is judged acceptable for a development
workstation default, and avoids introducing a fourth
language-version-manager pattern (`uv`/`fnm`/`rustup` already cover
Python/Node/Rust) for marginal freshness benefit.

```
serein hardware probe / dev status → go version go1.26.0 linux/amd64
```

## Conflict policy

If a Go toolchain is already installed (any source — the apt package or
a manually-installed tarball), the planner reports `NOOP`: *"A Go
toolchain is already installed; Serein will not install a second Go
tree or modify the existing one."* Serein never touches
`/usr/local/go` or any existing `GOROOT`.

## Documented alternative

A project that specifically needs a newer Go release than Ubuntu ships
can install the official tarball from `go.dev/dl` alongside the distro
package (Go supports multiple installed versions via `GOTOOLCHAIN`/
per-directory `go` binaries) — documented here as a manual option, not
a Serein-managed path in S3.
