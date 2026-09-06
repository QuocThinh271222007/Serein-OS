# S1R — Live Desktop Validation Evidence

This directory records the S1R validation pass: verifying claims made by
the S1 desktop layer against a genuine Ubuntu 26.04 environment rather
than fixtures alone. See `docs/desktop/known-limitations.md` for what S1
itself already flagged as unverified; this directory either resolves
those items with evidence or narrows them honestly.

## Validation environment

A disposable, isolated **WSL2** instance (`Ubuntu-26.04`, installed via
`wsl.exe --install -d Ubuntu-26.04`) was used as the validation target —
**not** the developer's own running WSL instance (a separate, pre-existing
`Ubuntu-24.04` instance that was never touched), and not the Windows host.
WSL2 was already present and enabled on this machine; no new
virtualization software was installed. This instance is disposable and can
be removed with `wsl --unregister Ubuntu-26.04` at any time.

Confirmed identity (`/etc/os-release` inside the instance):

```
PRETTY_NAME="Ubuntu 26.04 LTS"
VERSION="26.04 (Resolute Raccoon)"
VERSION_CODENAME=resolute
```

This is a real `apt`/`dpkg` Ubuntu 26.04 userland with live access to
`archive.ubuntu.com`/`security.ubuntu.com` — sufficient for **Tier B**
(package, dpkg-ownership, and installed-file validation) and, where a
nested Wayland session could be established, partial **Tier A** evidence
for KWin/Plasma runtime behavior. It has **no display manager control**
(SDDM cannot own a real VT/DRM device inside WSL), so SDDM's interactive
login flow (credential prompt, wrong-password handling) could not be
exercised — that remains a documented, non-blocking limitation, distinct
from "SDDM is broken" (see `sddm-validation.md`).

## Files

- `package-validation.md` — Validation A/B: package existence, dependency
  closure, dpkg file ownership of `/etc/xdg/kdeglobals` and
  `/etc/xdg/kwinrc`.
- `config-ownership-validation.md` — Validation B/C: the KConfig
  cascading model, confirmed against real package contents.
- `plasma-runtime-validation.md` — Validation C/D: Look-and-Feel KPackage,
  panel layout, color scheme, Konsole profile, KWin config.
- `sddm-validation.md` — Validation E: SDDM drop-in mechanism and
  precedence, confirmed against real shipped Kubuntu configuration.
- `known-blockers.md` — What remains BLOCKED after this pass, and why.
