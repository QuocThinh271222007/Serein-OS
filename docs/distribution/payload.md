# Serein Media Payload (S7.0 Sections 23-27, 62-63)

## What "payload" means here

Proof that S0-S6.5's work can be embedded on distribution media -
**never** a full worktree copy (Section 24), and **never** a claim that
the payload has been installed into any target OS (Section 55) - see
`docs/distribution/known-limitations.md`.

## Two independent pieces

1. **Resource entries** (`serein.distribution.payload.collect_resource_entries`)
   - the declarative, non-Python resource trees, hashed directly from
   the repository:

   ```python
   PAYLOAD_RESOURCE_ROOTS = ("desktop", "development", "hardware", "profiles", "schemas")
   ```

   - `desktop/` - S1 desktop assets (color schemes, Konsole/KWin/SDDM
     config, Plasma look-and-feel).
   - `development/` - S3 dev manifests (Git config template, Zed
     settings).
   - `hardware/` - S2 hardware defaults (zram-generator config).
   - `profiles/` - cross-phase profile manifests (`ai`, `balanced`,
     `battery`, `core`, `cyber`, `desktop`, `dev`).
   - `schemas/` - every JSON Schema contract across S0-S7.0, including
     Focus's own (`focus-plan.schema.json`,
     `focus-capabilities.schema.json`, `focus-transition.schema.json`)
     - this is how "Focus schemas/policy resources" (Section 63) are
     accounted for without a separate top-level `focus/` resource
     directory (Focus keeps its policy *logic* as Python, not static
     data files).

2. **The built wheel** (`serein.distribution.payload.build_wheel`,
   `python -m build --wheel --no-isolation`) - `src/serein/**`, which is
   where the AI (`src/serein/ai/`), Cyber (`src/serein/cyber/`), Veil
   (`src/serein/veil/`), and Focus (`src/serein/focus/`) subsystems keep
   their declarative manifests *as Python modules* rather than separate
   data trees. As of S7.0R, `serein.distribution.build.run_build` calls
   `build_wheel` and `inspect_wheel_contents` as part of every canonical
   build and embeds the result via `wheel_artifact` at
   `serein/payload/packages/<wheel filename>` - real media assembly,
   not merely a helper function available somewhere (Section 21-22 of
   the S7.0R corrective). `--no-isolation` keeps this fast and
   network-free (this interpreter's already-installed `setuptools`/
   `wheel`, never an isolated build environment needing a PyPI fetch) -
   never invoked by `pytest`/`ruff`/`mypy` themselves, since neither
   imports `build.run_build` with its wheel-building behavior active
   without a caller opting in. Never uploaded anywhere - the project
   stays `Private :: Do Not Upload` (`pyproject.toml`).

   `PayloadArtifact` (`entry` + `source_path`) is the abstraction that
   makes this safe: the public payload manifest only ever contains
   `entry` (path/sha256/size_bytes); `source_path` (the wheel's real,
   build-host-specific location under `build/work/wheel/`) is
   build-time-only and never serialized anywhere -
   `tests/test_distribution.py::TestWheelPayload::test_wheel_artifact_source_path_never_in_manifest_dict`
   regresses this directly.

## Exclusions (Section 24)

`_EXCLUDED_DIR_NAMES` in `payload.py` walks past `.git`, `__pycache__`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.venv`/`venv`/`env`,
`node_modules`, `.idea`, `.vscode`, `build`, `dist`, `cache` wherever
they appear under an allowlisted root; `_EXCLUDED_SUFFIXES` drops
`.pyc`/`.pyo`/`.log`. `tests/test_distribution.py::TestPayload` regresses
all of this directly (git metadata excluded, no `tests/` entries,
developer caches excluded, no secrets, deterministic hashes).

## Integrity (Section 54)

Every embedded file gets a `PayloadEntry(path, sha256, size_bytes)`;
`PayloadManifest.to_dict()` matches
`schemas/distribution-payload-manifest.schema.json` and is written onto
the media at `serein/payload-manifest.json`
(`serein.distribution.models.PAYLOAD_MANIFEST_PATH`). The read-only
inspector (`serein.distribution.inspect`) re-hashes every entry against
the file actually present on the medium and fails if any hash does not
match.

## Determinism (Section 17)

`build_payload_manifest` produces byte-identical manifest content for
identical `(source_commit, repo_root, roots)` inputs -
`tests/test_distribution.py::TestPayload::test_payload_hashes_deterministic`
regresses this. Full logical reproducibility (same base + same Serein
commit + same tool versions -> same content) follows from this plus the
pinned base image and versioned builder/overlay identifiers in
`serein.distribution.models` (`BUILDER_VERSION`, `OVERLAY_VERSION`) -
see `docs/distribution/iso-build.md` for the reproducibility contract
in full.
