# Serein Identity Architecture

## Design language: Quiet Velocity

Four core attributes govern every branding/UX decision: **Quiet**
(calm hierarchy, restrained color, minimal motion), **Fast**
(immediate interaction, lightweight components), **Focused** (low
chrome, clear primary actions), **Adaptive** (aware of future
workspace/resource-mode state, never fabricating it before it exists).

The UI may draw *philosophical* inspiration from tools like Zed
(compact, immediate, keyboard-oriented, low visual noise) - never
their logo, palette, layout, icons, or any pixel-identical
composition.

## Single sources of truth

| Concern | Canonical source | Never do this instead |
|---|---|---|
| Color/motion/visual-ratio values | `branding/tokens/design-tokens.json`, loaded via `serein.branding.tokens.load_design_tokens()` | Hardcode a hex literal in a GRUB/Plymouth/desktop file |
| Which branding assets exist, their purpose/format/status/provenance | `src/serein/branding/manifest.py` (`ASSETS`) | A second, drifting asset inventory in docs |
| ASCII/Unicode terminal fallback mark | `branding/terminal/serein-mark.txt` | A second, differently-drawn mark elsewhere |

Every other document under `branding/*/README.md` is a map into the
manifest, not an independent source of truth.

## Layout

```
branding/
  tokens/     design-tokens.json (shipped)
  terminal/   serein-mark.txt (shipped - the only asset that needed no
              external visual-asset provider, since it is pure text)
  logo/       master SVG + monochrome derivative (pending asset request)
  wallpaper/  default desktop/SDDM background (pending asset request)
  boot/       Plymouth mark + GRUB mark (both deterministic derivatives
              of the master logo, pending on it)
  icons/      small app/favicon icon (deterministic derivative, pending)
```

`branding` is a `serein.distribution.payload.PAYLOAD_RESOURCE_ROOTS`
entry (media-embeddable), exactly like `desktop`/`development`/
`hardware`/`profiles`/`schemas` - no new payload mechanism was
invented.

## Logo direction (not yet realized - see asset-handoff contract below)

A polygonal water droplet whose internal geometry/negative space
suggests an "S" - droplet recognizable first, "S" secondary,
~7-9 major facets, no literal typed "S" pasted inside, works
monochrome, works at 16-32px, works as a terminal approximation, works
on dark/light backgrounds. See `src/serein/branding/manifest.py`'s
`serein-logo-primary` entry for the full requirement text.

## Asset-handoff contract

This project does not invent or commit a final visual asset without
an approved source (Section 13 of the Phase-7-completion brief). An
asset registered with `status="pending_asset_request"` in the
manifest has no file at its listed `repo_path` yet - `test_branding.py`
enforces this directly (`test_pending_assets_have_no_file_on_disk_yet`).
The consolidated `ASSET_REQUEST_BATCH` for the two assets that
genuinely need external visual-design work (the master logo and the
default wallpaper - every other pending asset is a *deterministic
derivative* of the master logo, generated once it exists, never a
separate request) is issued alongside the Phase-7 completion report.

## Accessibility

`design-tokens.json`'s palette is a starting point, not permission to
color every element - Section 6's own "~90% neutral / ~8% subtle
accent / ~2% strong focus/status" ratio is encoded as
`visual_ratio` in the token file itself, so a future consumer can
check its own composition against it programmatically. Any contrast
adjustment a future consumer makes must be documented at the point it
is made, never silently.
