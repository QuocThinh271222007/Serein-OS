# Serein branding

The canonical home for Serein's visual identity ("Quiet Velocity" - see
`docs/branding/architecture.md` and `docs/adr/0032-serein-design-identity-system.md`).

Every asset shipped or referenced here is registered in
`src/serein/branding/manifest.py` (`ASSETS`), which records each
asset's purpose, format, whether it is a source-of-truth or a
generated derivative, dimensions, licensing/provenance, and intended
contexts. That module - not this README - is the authoritative,
tested inventory; treat these per-directory READMEs as a map into it.

## Layout

- `tokens/` - `design-tokens.json`, the single canonical source of
  Serein's color/motion/visual-ratio values. Loaded via
  `serein.branding.tokens.load_design_tokens`.
- `logo/` - the master vector logo and its deterministic derivatives.
  **No approved logo asset exists yet** - see
  `src/serein/branding/manifest.py` for the pending asset requests.
- `wallpaper/` - the default desktop wallpaper. **No approved asset
  exists yet.**
- `boot/` - Plymouth and GRUB marks, derived from the master logo once
  it exists.
- `terminal/` - `serein-mark.txt`, the mandatory ASCII/Unicode
  terminal fallback mark (S7.2 Section 12) - this one already ships,
  since it does not require an externally-provided visual asset.
- `icons/` - small/app-icon-sized derivatives of the master logo.

## Asset handoff contract

Per S7.2 Section 5, this project does not invent or commit a final
visual asset without an approved source. An asset registered with
`status="pending_asset_request"` in the manifest has no file at its
listed `repo_path` yet, and none is expected there until that request
is fulfilled. `src/serein/branding/manifest.py::pending_asset_requests()`
returns the current outstanding list.
