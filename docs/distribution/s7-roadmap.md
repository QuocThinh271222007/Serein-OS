# S7 Roadmap (Section 1)

```
S7.0  Bootable ISO prototype        (this repository)
S7.1  Installer integration          (not started)
S7.2  First-boot provisioning         (not started)
S7.3  Recovery / repair / fallback     (not started)
```

## S7.0 - what this phase delivers

- A pinned, checksum-verified (and signature-authenticated at the
  contract level) upstream Ubuntu 26.04 base image contract.
- A rootless, single-canonical-entrypoint ISO remaster pipeline
  (extract -> overlay -> payload -> rebuild -> manifest).
- A versioned, integrity-checkable Serein payload (never a full
  worktree copy).
- Read-only structural ISO/tree inspection.
- A bounded, positive-evidence QEMU boot-smoke harness.
- Extensive Layer A safety regressions (path traversal, autoinstall
  default, credentials, manifest schema conformance).

See `docs/distribution/known-limitations.md` for exactly what real
(Layer B) evidence does and does not exist yet from this pass, and the
one-command follow-up (installing build tooling in the already-present
WSL2 environment) needed to complete it.

## S7.1 - Installer integration (future, not started)

Would build on S7.0's payload/base-image contract to actually make the
Subiquity-based installer place Serein's payload into a real target
installation - late-commands, package installation into the target
root, and the Discover -> Resolve -> Plan -> Validate -> Apply ->
Verify -> Record lifecycle (`docs/architecture/installer-contract.md`)
applied to a real disk for the first time in this repository's history.
Nothing in S7.0 pre-empts this - `distribution/boot/qa-serial-entry.cfg`
and the boot-smoke harness never install to any disk (Section 92).

## S7.2 - First-boot provisioning (future, not started)

Would add a `serein-firstboot`-style mechanism to apply the desktop/
hardware/dev/ai/cyber/veil/focus profile resources S7.0 merely *embeds*
today into a freshly-installed target system. Explicitly out of scope
for S7.0 (Section 56).

## S7.3 - Recovery / repair / fallback (future, not started)

Would add recovery partition/restore-image/rollback capability.
Explicitly out of scope for S7.0 (Section 58-60) - no recovery
partition, no A/B rootfs, no OSTree/image-based conversion.

## S8 boundary (for context, unchanged by this phase)

Per `docs/roadmap.md`'s "Architecture invariant across all phases":
Serein integrates mature upstream components first, measures, and only
replaces them when there is a demonstrated need. S7.0's own research
(`docs/distribution/upstream-installer-research.md`) applies this
directly to the livecd-rootfs question - S7.0 remasters a verified
release ISO rather than adopting livecd-rootfs, and defers that
adoption decision to S8, contingent on measured maintenance cost.
