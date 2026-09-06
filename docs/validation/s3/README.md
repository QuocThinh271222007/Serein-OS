# S3 — Development Workstation Live Validation Evidence

This directory records the live Ubuntu 26.04 evidence gathered while
authoring S3's package manifest (`src/serein/development/packages.py`).
It is **Tier B** evidence, matching S1R/S2R's own definition of that
term: real `apt`/`dpkg` package-archive access, real installed-binary
paths, and real dependency-closure simulation — but not a full desktop
session, not real container-daemon behavior, and not GPU/AI-toolkit
evidence (deferred to S4).

## Validation environment

A disposable, isolated **WSL2** instance (`Ubuntu-26.04`, installed via
`wsl.exe --install -d Ubuntu-26.04 --no-launch`), matching S1R/S2R/S2RM's
exact methodology — **not** the developer's own running WSL instance
(`Ubuntu-24.04`, never touched), and not the Windows host. Removed
(`wsl.exe --unregister Ubuntu-26.04`) after use.

Confirmed identity:

```
PRETTY_NAME="Ubuntu 26.04 LTS"
VERSION="26.04 (Resolute Raccoon)"
VERSION_CODENAME=resolute
```

`apt-get update` ran clean (all `Hit:`) against `archive.ubuntu.com`/
`security.ubuntu.com` before any package check.

## Files

- `package-validation.md` — the package-existence table, the two real
  corrections found (`p7zip-full`→`7zip`, `fd-find`/`bat` binary-name
  quirks), the excluded-`yq`-package investigation, and the final
  corrected dependency-closure simulation.

## What this validation does and does not prove

**Proves:** every `ubuntu-repository`-sourced tool in
`packages.py`/`default_apt_packages()` is a real, installable Ubuntu
26.04 package with the exact name used in the manifest; the full
33-package default set has a satisfiable dependency closure with no
conflicts or unexpected removals; three specific binary-naming
surprises (`7zip`, `fdfind`, `batcat`) are real, not assumed.

**Does not prove:** that `official-upstream-binary`/
`language-bootstrap-tool` tools (uv, rustup, fnm, pnpm, Zed) install
correctly — their installers were deliberately never executed (S3's
"no host mutation" rule applies to the *validation* environment too,
not only to the developer's own machine; see `known-limitations.md`);
that any of these tools work under Wayland/X11 in a real desktop
session; or anything about GPU/container-toolkit behavior (S4 scope).
