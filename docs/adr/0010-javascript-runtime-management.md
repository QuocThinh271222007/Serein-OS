# ADR-0010: JavaScript Runtime Management (fnm + pnpm, not nvm/Corepack)

## Status

Accepted

## Context

Ubuntu's `nodejs`/`npm` packages exist but using them as the primary
developer runtime would tie every project on the machine to one Node
version, contradicting normal per-project Node-version needs. A
user-level version manager is required. Three real candidates exist:
`nvm` (the historical default, a Bash function, not a binary — no native
Windows/WSL-cross-tooling story, slow shell startup), `fnm` (Rust,
single-purpose, 10-40x faster than nvm, native `.nvmrc` support), and
`mise` (a polyglot single-binary manager covering Node/Python/Go/Rust/
tasks, gaining significant 2026 momentum as an emerging default).

Separately: Node's TSC voted to stop bundling Corepack (experimental-only
in Node 24, fully removed in Node 25+), so a pnpm strategy that depends
on Corepack is not forward-compatible.

## Decision

- **`fnm`** is Serein's preferred Node version manager. Official
  installer: `fnm.vercel.app/install` (downloads a prebuilt binary,
  user-level, no `sudo`).
- **`pnpm`** is installed via its own standalone installer
  (`get.pnpm.io/install.sh`), independent of Corepack.
- **`npm` is never removed** — it ships with Node itself and remains
  available; Serein does not manage it separately.
- **Conflict policy:** if any other Node manager (`nvm`, `mise`) is
  already present, the planner reports `BLOCKED` — *"Existing Node
  management detected; choose which manager Serein should integrate
  before provisioning another"* — rather than layering `fnm` on top.

## Why fnm over mise

`mise` is a genuinely strong, increasingly popular choice — but it also
manages Python and Rust, the exact two ecosystems ADR-0009 and this
document's Rust counterpart already assign to `uv` and `rustup`
specifically. Adopting `mise` for Node only, while using different
tools for Python/Rust, would mean `mise` sits installed on every Serein
workstation with most of its surface area unused, and would create a
second, overlapping version-management authority for any project that
later *does* want `mise` to manage Python/Rust too. `fnm` does exactly
one job — matching Serein's existing "conflict-avoidance" principle from
S2 (no two managers claiming the same territory) applied here as "no two
managers claiming *adjacent* territory" as well. `mise` remains a
reasonable choice for a user who wants a single polyglot manager instead
of Serein's per-language tools — that user's existing `mise` install is
detected and respected, not fought.

## Consequences

- Three real Node-manager code paths exist in `node.py`/`planner.py`
  (fnm, mise, nvm) purely for *detection*; only fnm is ever a Serein
  `APPLY` target.
- If `mise`'s polyglot approach continues gaining share to the point it
  becomes the de facto standard across the ecosystem Serein targets,
  this ADR — and possibly ADR-0009/the Rust strategy — should be
  revisited together, not piecemeal.

## Alternatives considered

**`nvm`.** Rejected: shell-function-based (cannot be probed as a binary
the way every other S3 tool is), slower, and superseded in most current
recommendations by `fnm` specifically as "the fast nvm replacement."

**Corepack-managed pnpm.** Rejected: Node's own TSC decision to remove
Corepack in Node 25+ makes this a dead end for anyone updating Node.
