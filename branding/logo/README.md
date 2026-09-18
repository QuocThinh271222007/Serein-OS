# branding/logo/

Expected files (see `src/serein/branding/manifest.py` for the full
registry entry of each):

- `serein-logo-primary.svg` - the master vector logo: a polygonal
  water droplet whose internal geometry/negative space suggests an
  "S" (~7-9 major facets). Source of truth for every other logo
  variant. **Not yet provided** - pending an asset request to the
  project's visual-asset provider.
- `serein-logo-monochrome.svg` - a flat single-color (`currentColor`)
  derivative of the primary logo, for favicon/GRUB/small-icon
  contexts. Deterministically generated from the primary once it
  exists - never hand-invented separately.

Nothing in this directory is final branding until the primary asset
request above is fulfilled and the file actually lands here.
