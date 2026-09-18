# Release / Update Infrastructure Architecture

Phase-7-completion Section 42-53. Backend is the real Ubuntu/Debian
APT ecosystem (Section 42 - "DO NOT build a custom package manager").

## What is real and tested in this round

- **Version model** (`serein.release.version`, Section 51-52): one
  canonical `ReleaseVersion` (`serein_version`/`channel`/
  `source_commit`), reusing `serein.__version__` and
  `serein.distribution.models.BuildManifest.source_commit` directly -
  never a second, independently-maintained copy of either. A built
  ISO's own manifest now also carries `serein_version` (Section 52 -
  "A built ISO should carry: Serein release version, source commit,
  build timestamp, payload manifest version" - the last three already
  existed; this round added the first).
- **Update channels** (`serein.release.channels`, Section 44):
  stable/beta/dev, `stable` the fixed default, never `dev`.
- **Migration framework** (`serein.release.migration`, Section 53): a
  generic, ordered, checkpointed apply/verify/rollback runner. No real
  migration exists yet - nothing has shipped that needs one - proven
  with synthetic migrations in `tests/test_release.py` instead of
  fabricated production content.
- **Signed repository tooling** (`serein.release.repository`, Section
  43/49/50): real `dpkg-scanpackages`/`gpg` invocations (never a
  custom, insecure ad-hoc format) to scan a `.deb` directory, render a
  `Release` file with a real SHA256 of the indexed `Packages` file,
  and sign it (`--clearsign` -> `InRelease`, or `--detach-sign` ->
  `Release.gpg`). `render_apt_sources` emits the modern DEB822
  `.sources` format with an explicit `Signed-By:` keyring path -
  never the deprecated global `apt-key` pattern (Section 43).
  `tests/test_release.py` proves this against **real, disposable,
  ephemeral ED25519 keys** generated fresh per test into an isolated
  `GNUPGHOME` (never the real host keyring, never a committed key -
  Section 50): a valid signature is accepted, a wrong key is
  rejected, an unsigned file is rejected, tampered signed content is
  rejected, and both the clearsigned and detached-signature forms
  round-trip correctly.

## What is deliberately not built in this round

- **`serein update status|check|plan|apply|channel` CLI** (Section
  45): not implemented as a CLI surface yet. The version/channel model
  it would read already exists and is tested; wiring a CLI around it
  is a small, well-scoped, low-risk follow-up (mirrors
  `serein.recovery`'s own `status`/`doctor`/`plan` + separate mutating
  entrypoint pattern almost exactly) deliberately deferred to keep
  this round's scope to what could be built AND genuinely verified
  (signed round-trip, not just syntax) given the time available.
- **A real archive keyring / production repository domain / signing-
  key ceremony** (Section 93 explicitly allows deferring these - "real
  production APT domain deployment, production signing key ceremony").
- **`serein update apply` actually invoking `apt-get`/`dpkg` against a
  real system**: deliberately never attempted even experimentally -
  Section 90 forbids altering host APT configuration during
  tests/validation, and there is no real Serein package repository to
  point it at yet regardless.
- **Automatic update-check timer / notification** (Section 46): no
  systemd timer unit exists yet. Design constraint already honored by
  construction: nothing in this round added any persistent daemon or
  polling process (Section 26/72 - "very few permanently resident
  Serein services").

## Backlog

| ID | Area | Severity | Description | Reason deferred | Future validation |
|---|---|---|---|---|---|
| `SEREIN-UPDATE-CLI-PENDING` | release / update | non-blocking | No `serein update status\|check\|plan\|apply\|channel` CLI surface exists yet. | Scoped out to prioritize proving the harder, more novel piece (real signed-repository round-trip) with genuine test coverage in the time available. | Build the CLI following the exact `serein.recovery` read-only/mutating-entrypoint pattern; `check`/`plan` can query a real local `file://` test repository built with `serein.release.repository` end-to-end. |
| `SEREIN-UPDATE-TIMER-PENDING` | release / update | non-blocking | No systemd timer unit exists for periodic update checking (Section 46). | Depends on `SEREIN-UPDATE-CLI-PENDING`'s `check` command existing first. | A oneshot `serein-update-check.timer`/`.service` pair, mirroring `serein-firstboot.service`'s own minimal-footprint oneshot design. |
| `SEREIN-UPDATE-ROLLBACK-CLASSIFICATION-PENDING` | release / update | non-blocking | Section 48's honest rollback classification ("do not claim universal rollback if APT history/package availability makes it impossible") has no real implementation yet - only the migration framework's own per-migration `rollback` field exists. | Requires a real repository with real package history to classify against - premature before `SEREIN-UPDATE-CLI-PENDING`. | Build once a real (even if local/test-only) multi-version repository exists to validate rollback classification against. |
