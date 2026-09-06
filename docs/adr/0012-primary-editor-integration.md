# ADR-0012: Primary Editor Integration (Zed, upstream-first, no forced config)

## Status

Accepted

## Context

Zed is the owner's actual working editor and Serein's stated preferred
IDE. Zed has no official Ubuntu package or APT repository (a
community-maintained, non-official APT repo exists but is explicitly not
official and is adding an authentication requirement); the official,
vendor-documented installation method for Linux is a script at
`zed.dev/install.sh` that installs a prebuilt binary under the user's
home directory (`~/.local/`) with no `sudo` step.

## Decision

- **Detection only in S3**: `serein dev status`/`capabilities`/`plan`
  detect Zed (`zed --version`, falling back to the `~/.local/bin/zed`
  marker path since that directory is not guaranteed to be on every
  shell's `$PATH`) and report a plan action describing the official
  installer — never executed by S3.
- **No Flatpak.** Not chosen: it was not the path the owner's workflow
  or Zed's own primary documentation centers on, and would add a second
  packaging system's overhead for one application.
- **Configuration ownership follows S1's model exactly**: Serein ships a
  recommended settings template at `development/zed/settings.json`
  (dark theme, format-on-save, sane terminal defaults) that a future
  Apply step would place at `~/.config/zed/settings.json` **only for a
  user with no existing settings file** — mirroring the Look-and-Feel
  first-login mechanism S1R validated for the desktop layer. Serein
  never overwrites an existing Zed config on any subsequent run.
- **No theme extension is built.** "Serein Dark" was a KDE Plasma color
  scheme (S1); Zed's own theme system is unrelated, and building a
  custom Zed theme extension is out of S3's scope. The template instead
  selects one of Zed's own built-in dark themes ("One Dark") as the
  closest practical alignment — documented as a pragmatic choice, not a
  perfect rebrand.
- **Extensions are documented, not installed.** Recommended extensions
  for Python/TypeScript/Rust/Go/C++/Docker are named in
  `docs/development/editor-strategy.md`; none are installed
  automatically, since Zed's own extension marketplace is the correct,
  user-driven mechanism for that.

## Consequences

- Zed's own update mechanism remains authoritative — Serein never
  competes with it and never pins a version.
- Users on WSL get accurate capability reporting (Zed is a GUI
  application; installing the binary is still meaningful there via
  WSLg, but Serein does not claim GUI usability it cannot verify — see
  docs/development/known-limitations.md).

## Alternatives considered

**VS Code as an equal default.** Rejected: the owner's explicit
preference is Zed; VS Code remains documented as an optional,
user-choice editor (`docs/development/editor-strategy.md`) rather than
a second default Serein actively provisions.

**A Serein-branded Zed theme extension.** Rejected for S3 as
disproportionate scope for a detection/planning phase; revisit only if
a measured need emerges (Integrate → Measure → Replace).
