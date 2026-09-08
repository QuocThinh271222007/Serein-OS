# Licensing and Release Boundary (S7.0 Section 26-27) — CRITICAL

## No project license exists yet

`pyproject.toml` deliberately carries no `license` table and the
repository has no `LICENSE` file - this was already true before S7.0 and
remains unchanged by it:

```toml
# No license has been selected yet by the project owner. Do not add a
# `license` table or LICENSE file until that decision is made.
classifiers = ["Private :: Do Not Upload"]
```

**Therefore a public Serein ISO release is out of scope for S7.0.**
Every artifact `src/serein/distribution/` and `distribution/scripts/`
can produce is a **private, internal development alpha**, never a
public release:

- No `LICENSE` file was added by this phase
  (`S7_0_LICENSE_FILE_CREATED_COUNT=0`).
- No public release, GitHub Release, or version tag was created
  (`S7_0_PUBLIC_RELEASE_COUNT=0`).
- No package repository (APT or otherwise) was created (Section 61).
- The built wheel is never uploaded anywhere - `pyproject.toml`'s
  `classifiers = ["Private :: Do Not Upload"]` is preserved unchanged.
- `RELEASE_CHANNEL = "alpha"` (`serein.distribution.models`) is the only
  channel this phase's build manifest schema accepts
  (`schemas/distribution-build-manifest.schema.json` -
  `"release_channel": { "enum": ["alpha"] }`).

## Ubuntu attribution / trademark boundary (Section 27)

`distribution/overlay/serein/README.txt` (embedded on every built
medium) states explicitly:

> "This medium is based on Ubuntu, an operating system published by
> Canonical Ltd. Ubuntu's own copyright and license notices are
> preserved unmodified elsewhere on this medium."

Nowhere in this repository's documentation, code, CLI output, or media
content does Serein claim to be an official Ubuntu flavor or claim
Canonical endorsement. S7.0's extraction/overlay approach
(`docs/distribution/iso-build.md`) never removes or modifies Ubuntu's
own copyright/license notices embedded in the base image.

## When this changes

A public release becomes possible only after the project owner selects
a license and adds it deliberately (a decision outside this phase's
scope - `docs/distribution/known-limitations.md` records this as a
standing release blocker, not a task S7.0 attempted to resolve).
