# Production vs. QA Install Modes (S7.1 Sections 6-7, 35-36)

## Production: never zero-touch

```text
DEFAULT_AUTOINSTALL_DISABLED=true
DEFAULT_ZERO_TOUCH_INSTALL=false
```

Production Serein media (the S7.0 `serein-alpha-26.04-amd64.iso`)
never boots with `autoinstall` on its default kernel command line,
never automatically erases any disk, and never contains a
configuration that silently chooses a target disk. If a user boots
Serein and does nothing, `DISK_MODIFICATION_COUNT=0`. Production
interactive installation must display the target's model, size,
serial/stable ID (where available), and current partitions/filesystems
before any destructive summary is shown, and confirmation must occur
*after* plan generation - never a bare "Continue?" with no target
identity shown (Section 36).

`serein.installer.renderer.render_autoinstall_yaml` (and
`render_autoinstall_storage_config`) enforce this at the code level:
every entrypoint requires an explicit `qa_mode=True` keyword argument
and raises `RendererError` without it. This is a deliberate tripwire -
a future caller cannot accidentally wire autoinstall rendering into a
production path without a visible, reviewable change.

## QA: automated, but only against synthetic disks

```text
QA_AUTOINSTALL_ALLOWED=true
PRODUCTION_AUTOINSTALL_DEFAULT=false
```

Automated installation is permitted **only** inside the S7.1 QA/CI
environment (`installer-smoke.yml`), and only against newly-created
qcow2 image files inside the CI workspace - never
`/dev/sda`/`/dev/nvme0n1`/`/dev/disk/by-id/<physical-host-disk>` passed
into QEMU. `python -m serein.installer render-autoinstall` requires an
explicit `--qa-allow-autoinstall` flag matching the Python-level
`qa_mode=True` tripwire.

The rendered `autoinstall.yaml` is embedded into a **separate** ISO
variant (`serein-alpha-26.04-amd64-qa-install.iso`,
`serein.installer.isoprep.prepare_qa_install_iso`) - it is never baked
into the S7.0 production or QA-serial-boot ISOs. See
`docs/installer/vm-validation.md` for how this variant is built and
used.

## Runtime-only QA credentials (Section 35)

```text
QA_CREDENTIAL_GENERATED_AT_RUNTIME=true
QA_CREDENTIAL_NOT_EMBEDDED_IN_PRODUCTION_ISO=true
REUSABLE_PASSWORD_HASH_COMMITTED=false
```

`serein.installer.payload.generate_qa_credential` generates a fresh,
random password (`secrets.token_urlsafe(24)`) and hashes it via real
`openssl passwd -6` at CI runtime - never a hardcoded or reusable hash.
Python's stdlib `crypt` module was removed in 3.13, which is why this
shells out to `openssl` (already installed on every Ubuntu runner)
rather than depending on a module that no longer exists. If `openssl`
is unavailable or produces unexpected output, the function returns
`None` (fail-soft) rather than falling back to any fixed value - the
caller must then refuse to render an autoinstall config at all.

**Known limitation**: the plaintext password is passed as a process
argument to `openssl passwd`, which could in principle be visible via
a process listing for the brief duration of that one command. This is
an accepted risk only inside the single-tenant, ephemeral Layer-B CI
VM this function is intended for - never for interactive or production
use, where this function is never called at all (see
`docs/installer/known-limitations.md`).

The plaintext password is never written to a file, never logged
(`python -m serein.installer render-autoinstall` prints only a
generic "QA credential generated at runtime" confirmation, never the
value itself), and never committed - only the resulting crypt hash
goes into the rendered `autoinstall.yaml`, which is itself only ever
embedded in the ephemeral QA-install ISO variant, never uploaded as a
Layer-B evidence artifact.
