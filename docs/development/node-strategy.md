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
  and `mise` (a real binary) are both detected. If either is already
  present, `node.manager` plans `BLOCKED`: *"Existing Node management
  detected; choose which manager Serein should integrate before
  provisioning another."* Serein never fights existing tooling by
  layering `fnm` on top.

## Target outcome

```
Node runtime      version-manager controlled (fnm)
pnpm              available, not Corepack-mediated
project-local     .nvmrc/.node-version-style per-project pinning possible
root npm installs never (`sudo npm install -g` is never a Serein action)
```

## Cache locations (documented, not moved)

`pnpm`'s content-addressable store lives under
`$XDG_DATA_HOME/pnpm/store` (or `~/.local/share/pnpm/store`) by pnpm's
own default. `fnm`'s installed Node versions live under `~/.local/share/fnm`
or `~/.fnm` depending on installer version. Serein does not relocate
either.
