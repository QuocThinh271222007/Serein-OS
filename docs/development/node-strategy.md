# Node.js Strategy

See ADR-0010 for the full decision record and why `fnm` was chosen over
`nvm`/`mise`. Summary:

- **Ubuntu's `nodejs`/`npm` packages are never the primary developer
  runtime** — a version manager governs the actual Node version used by
  projects, since a single system-wide Node version cannot serve every
  project's needs.
- **`fnm`** is Serein's preferred Node version manager. Official
  installer: `fnm.vercel.app/install` (documented, never executed by
  S3). No `sudo`, user-level only.
- **`pnpm`** is installed via its own standalone installer
  (`get.pnpm.io/install.sh`) — **not** via Corepack, which Node's own
  TSC voted to stop bundling (experimental-only in Node 24, removed in
  Node 25+). `npm` remains available with Node and is never removed or
  disabled.
- **Conflict policy**: `nvm` (detected via the `~/.nvm/nvm.sh`
  filesystem marker — it is a shell function, not a probeable binary)
  and `mise` (a real binary) are both detected. Serein never fights
  existing tooling by layering `fnm` on top of it.

## Node manager conflict state machine (S3R)

`NodeStatusInfo.managers` is the single source of truth for which
managers (`fnm`, `mise`, `nvm`) are present — both the planner and the
doctor derive their decisions from it, so they can never enumerate
managers differently. `node.manager`'s plan status is a strict function
of that tuple:

| Detected managers      | `node.manager` status | Rationale                                             |
|-------------------------|-----------------------|--------------------------------------------------------|
| none                     | `APPLY` (install fnm)  | Nothing to conflict with.                              |
| `fnm` only               | `NOOP`                 | Serein's preferred manager is already present.         |
| exactly one, not `fnm`   | `BLOCKED`              | Don't layer fnm on top of an existing, working manager. |
| more than one            | `BLOCKED`              | Ownership is already ambiguous; adding a third doesn't help. |

The doctor's `development_node_manager_conflict` check uses a
different, narrower threshold — it only `WARN`s when **more than one**
manager is present, since a single non-`fnm` manager is a normal,
supported setup (the planner just won't provision a second one), not a
conflict worth flagging.

**pnpm dependency**: if `node.manager` is `BLOCKED` (Node runtime
ownership unresolved) and `pnpm` isn't already installed, `node.pnpm`
is also `BLOCKED` rather than `APPLY` — installing pnpm standalone
while it's unclear which manager owns the Node runtime it will run
under risks a second ambiguous PATH/config source on top of an
already-ambiguous Node setup. An already-installed `pnpm` is always
reported `NOOP`, regardless of manager-conflict state — Serein never
re-litigates what's already there.

## Target outcome

```
Node runtime      version-manager controlled (fnm)
pnpm              available, not Corepack-mediated
project-local     .nvmrc/.node-version-style per-project pinning possible
root npm installs never (`sudo npm install -g` is never a Serein action)
```

## Future Apply hardening (documented now, not implemented)

No Apply engine exists in S3 — this is planning guidance for whenever
one is built, not current behavior. `fnm`'s official installer supports
a `--skip-shell` flag that skips writing its shell-init snippet into
the user's rc files; a future Serein-controlled `fnm` install should
use it and let a separate, explicit, user-visible step own any rc-file
edit, rather than an installer silently appending to `~/.bashrc`/
`~/.zshrc` as a side effect of "just installing a tool." Similarly, a
future `pnpm` install must treat its own shell/PATH setup step
(`pnpm setup`) as an explicit, separate, user-visible action, not
something bundled invisibly into "install pnpm."

## Cache locations (documented, not moved)

`pnpm`'s content-addressable store lives under
`$XDG_DATA_HOME/pnpm/store` (or `~/.local/share/pnpm/store`) by pnpm's
own default. `fnm`'s installed Node versions live under `~/.local/share/fnm`
or `~/.fnm` depending on installer version. Serein does not relocate
either.
