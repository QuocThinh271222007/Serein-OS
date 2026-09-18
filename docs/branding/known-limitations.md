# Branding/Identity - Known Limitations

## Fastfetch config has never run against a real fastfetch binary

Fastfetch is not installed anywhere in this development/CI
environment. `serein.branding.fastfetch.build_fastfetch_config`'s
output has only ever been reviewed by hand against Fastfetch's own
documented JSON config schema and confirmed to be syntactically valid
JSON (`tests/test_branding.py::TestFastfetch::test_config_is_valid_json`)
- it has never been rendered by a real `fastfetch` process. This
mirrors this project's own established precedent for
`distribution/systemd/serein-firstboot.service`
(`docs/firstboot/known-limitations.md`).

`FASTFETCH_RUNTIME_RENDER=NOT_PERFORMED` - real proof requires a real
installed/live Ubuntu-family system with `fastfetch` installed.

## Backlog

| ID | Area | Severity | Description | Reason deferred | Future validation |
|---|---|---|---|---|---|
| `SEREIN-FASTFETCH-LOGO-STAGING-PENDING` | branding / fastfetch | non-blocking | `build_fastfetch_config`'s logo source points at `/etc/serein/branding/terminal-mark.txt`, a real first-boot-owned path, but nothing yet writes the terminal mark there - a small follow-up to `step_initialize_directories` (which already writes `/etc/os-release`/`/etc/issue`/`/etc/issue.net` there via the exact same pattern). | Scoped out of the initial Fastfetch integration to keep that change small and independently reviewable. | Extend `step_initialize_directories` to also write the terminal mark, then confirm Fastfetch actually resolves the logo on a real installed system. |
| `SEREIN-FASTFETCH-PACKAGE-INSTALL-PENDING` | branding / fastfetch | non-blocking | Nothing yet installs the `fastfetch` package itself or places the generated config at `~/.config/fastfetch/config.jsonc` / `/etc/fastfetch/config.jsonc`. | Package installation and config placement is a desktop/first-login-provisioning concern, not yet wired to any Apply step. | Wire into `serein.desktop`'s package list and a config-installation step, then real-run `fastfetch` and confirm the actual rendered output. |
| `SEREIN-FOCUS-MODE-CONTRACT-PENDING` | branding / focus | non-blocking | Fastfetch's "Mode" field is a fixed "Balanced" placeholder - no Performance/Balanced/Efficiency/Isolated resource-mode state exists yet to read (Section 21 of the Phase-7-completion brief explicitly scopes the full resource allocator out of this phase). | The UI-state contract for resource modes is deliberately separate from resource-control implementation, and the latter does not exist yet. | Once a real resource-mode state exists (mirroring `serein.focus.runtime`'s own persistence pattern), read it here instead of the fixed placeholder. |
