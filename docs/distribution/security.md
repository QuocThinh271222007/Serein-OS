# Distribution Security Model (S7.0; Layer-B workflow hardening in S7.0R)

## Layer-B CI trust model (S7.0R Corrective A)

`.github/workflows/iso-smoke.yml` uses `pull_request` (never
`pull_request_target`) so it never runs with write-capable repository
secrets against untrusted feature-branch code; `permissions: contents:
read` is the only permission the workflow requests, and no repository
secret is referenced anywhere in it
(`tests/test_distribution.py::TestLayerBWorkflow::test_no_secrets_referenced`
regresses this). It only ever runs on an explicit `workflow_dispatch`
or on a pull request an authorized user has deliberately labeled
`run-iso-smoke` - never on an arbitrary PR's normal commits. The
checkout step pins the exact PR head SHA
(`github.event.pull_request.head.sha`, not the default merge ref), and
a dedicated verification step fails the job if the checked-out SHA
ever disagrees with that expected value - so a build manifest's
provenance can never silently drift from the reviewed commit.

## Checksum + signature trust chain (Section 10-11)

Required flow, enforced fail-closed in
`serein.distribution.base.verify_base_image`:

```
download -> sha256 verify -> only then extract
```

`verify_base_image` raises `BaseImageError` (never a silent
`False`/warning) if the base ISO file is missing or its sha256 does not
exactly match `distribution/base-image.json`'s pinned value.
`serein.distribution.build.run_build` calls this before any extraction
step and re-raises as `BuildError` - there is no code path from an
unverified base file to a build output.

### How the pinned checksum was itself verified authentic

Run during this S7.0 implementation pass, 2026-09-07, from a clean
scratch directory (not this repository, to avoid any chance of writing
a stray keyring into version control):

```bash
curl -fsSL -o SHA256SUMS     https://releases.ubuntu.com/26.04/SHA256SUMS
curl -fsSL -o SHA256SUMS.gpg https://releases.ubuntu.com/26.04/SHA256SUMS.gpg

# gpg --verify names the signer without needing the key first:
gpg --batch --verify SHA256SUMS.gpg SHA256SUMS
# -> "using RSA key 843938DF228D22F7B3742BC0D94AA3F0EFE21092"

# Fetch that exact key by fingerprint from Ubuntu's own keyserver (HTTP
# GET, not gpg's dirmngr, which had no outbound network path in this
# environment):
curl -fsSL -o cdimage-signing-key.asc \
  "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x843938DF228D22F7B3742BC0D94AA3F0EFE21092"
gpg --batch --import cdimage-signing-key.asc

gpg --batch --verify SHA256SUMS.gpg SHA256SUMS
# -> "Good signature from "Ubuntu CD Image Automatic Signing Key (2012)
#     <cdimage@ubuntu.com>""
# -> Primary key fingerprint: 8439 38DF 228D 22F7 B374  2BC0 D94A A3F0 EFE2 1092
```

This proves the checksum *value* pinned in `base-image.json` is
authentic (came from Canonical's own signed publication, not a guess or
an untrusted mirror) - it does **not** prove the actual 6.0 GB ISO file
has been downloaded and hash-verified in this environment, which is why
`base-image.json`'s `verified` field is honestly `false` (see
`docs/distribution/known-limitations.md`). `verify-base-image.sh`
re-derives this exact signature check (plus the real file's sha256)
against whatever was actually downloaded, every time it runs - the
research above is provenance for the pin, not a substitute for that
step.

### Trust path - what is and is not hardcoded

- `distribution/base-image.json`'s `signing_key_fingerprint` is the
  **only** thing pinned in this repository related to signing trust -
  a 40-hex-char OpenPGP v4 fingerprint, never a full key blob.
- The actual public key bytes are always fetched live from
  `keyserver.ubuntu.com` by that exact fingerprint - never embedded in
  the repository, never fetched from an arbitrary/unofficial keyserver.
- No Serein-controlled signing key exists anywhere in this phase
  (Section 32) - Serein never re-signs any Ubuntu boot component.

## Credential scanning (Section 42, 88)

`serein.distribution.safety.scan_tree_for_credentials` walks the
`distribution/` tree (and is also run against
`src/serein/distribution/` itself in
`tests/test_distribution.py::TestCredentialScan`) looking for
password/passwd/`ssh_private_key`/private-key-header/`API_KEY`/`TOKEN`
patterns, with a narrow allowlist for lines that are clearly
documentation *naming* the pattern (e.g. this file, or the pattern
table in `safety.py` itself) rather than an embedded secret. No
credential of any kind is committed anywhere in this phase - S7.0
deliberately avoids needing one at all (no installer password is set by
this repository; see `docs/distribution/boot-validation.md`).

## Autoinstall safety (Section 40-41, 87)

`serein.distribution.safety.scan_boot_config_for_default_autoinstall`
parses GRUB-style boot configuration into per-entry blocks and flags
any entry containing `autoinstall` on its kernel command line unless
its title is clearly marked QA/automation-only. The only `autoinstall`
usage anywhere in this repository's committed boot configuration is
the explicit example in `distribution/test-fixtures/grub-cfg-unsafe.cfg`,
which exists *specifically* to prove the scanner catches it -
`distribution/boot/qa-serial-entry.cfg` (the real QA boot template)
never sets `autoinstall` at all; it only adds `console=ttyS0` for
serial-log capture.

## Path safety (Section 68-69, 73-74)

Three operations share `serein.distribution.pathsafety`:

- **Payload assembly** (`payload.collect_resource_entries`) - every
  candidate file's resolved path is checked against its declared
  resource root before being hashed/embedded; a symlink planted inside
  an allowlisted resource directory that resolves outside the repo is
  silently excluded, never followed.
- **Overlay application** (`overlay.apply_overlay`) - every destination
  is checked against `OVERLAY_ALLOWLIST` (only `.disk/` and `serein/`
  may ever be written) *and* re-validated with
  `pathsafety.resolve_within` immediately before the write, so neither
  an out-of-scope destination root nor a `../`/symlink escape within an
  allowed root can succeed.
- **Cleanup** (`distribution/scripts/clean.sh`,
  `pathsafety.is_safe_cleanup_target`) - the only path ever passed to
  `rm -rf` is `${REPO_ROOT}/build`, re-derived and verified equal to
  itself after resolution before deletion; no environment variable is
  ever trusted as a deletion target (Section 74's "safe delete
  invariant").

## Host-identity exclusion from build manifests (Section 16, 67)

`serein.distribution.models.BuildManifest.to_dict()` only ever emits
the fields defined in `schemas/distribution-build-manifest.schema.json`
- none of which is a username, absolute path, or hostname.
`tests/test_distribution.py::TestManifest::test_manifest_never_contains_host_identifying_fields`
regresses this directly against the current host's own username/temp
path.
