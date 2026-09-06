# Editor Strategy

See ADR-0012 for the full decision record. Zed is Serein's primary,
preferred editor — matching the owner's actual workflow.

## Distribution

Official installer: `zed.dev/install.sh` — installs a prebuilt binary
under `~/.local/`, symlinks `~/.local/bin/zed`, writes a per-user
`.desktop` launcher. No `sudo`, no system-wide changes. No official
Ubuntu package or APT repository exists (a community-maintained repo
exists but is not official and is adding an authentication requirement
— not used by Serein). Never executed by S3; documented only.

## Configuration ownership

Serein ships a recommended settings template at
`development/zed/settings.json` (dark theme aligned as closely as Zed's
own theme system allows, format-on-save, sane terminal defaults). A
future Apply step would place this at `~/.config/zed/settings.json`
**only when no such file already exists** — the same first-login-only
mechanism S1R validated for the KDE desktop layer. Serein never
overwrites an existing Zed configuration on any subsequent run.

## Theme alignment (honest scope note)

"Serein Dark" (S1) is a KDE Plasma color scheme, unrelated to Zed's own
theme engine. Building a matching Zed theme extension is out of S3's
scope; the template instead selects one of Zed's own built-in dark
themes ("One Dark") as the closest practical alignment.

## Recommended extensions (documented only — none installed automatically)

| Language | Recommended Zed extension |
|---|---|
| Python | Zed's built-in Python language support (Pyright-based) |
| TypeScript/JavaScript | Zed's built-in TypeScript language support |
| Rust | Zed's built-in Rust support (rust-analyzer) |
| Go | Zed's built-in Go support (gopls) |
| C/C++ | Zed's built-in C/C++ support (clangd) |
| Docker | Community Dockerfile extension, if needed |

Most of the above ship as Zed's own built-in language support rather
than separate extensions — verify against Zed's current extension
marketplace before assuming any is required; none are forced.

## Optional editors

VS Code, Neovim, and JetBrains IDEs are not installed or made
mandatory. A user who prefers one of these keeps using it; Serein does
not become an editor-comparison project (Section 34 of the S3 brief).

## WSL note

Zed's binary can be installed under WSL, but running its GUI depends on
WSLg (or an X server) being available — `serein dev capabilities`
reports `zed_editor` as provisionable everywhere (installing the binary
always works) at `medium` confidence, since actual GUI usability is not
verifiable from a detection-only check.
