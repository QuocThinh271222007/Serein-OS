# S7.2 Handoff Contract (S7.1 Sections 27-28, 48)

After a real S7.1 installation:

```text
system installed
bootable
Serein core present
firstboot state = pending
```

## The marker

`serein.installer.payload.build_install_state_marker(source_commit,
source_media_version)` produces the content written to
`/etc/serein/install-state.json` on the freshly installed target (via
a base64-round-tripped `late-commands` entry in the rendered
`autoinstall.yaml` - `serein.installer.renderer._install_state_late_command`,
so the JSON content's own quoting never has to be hand-escaped into the
shell/JSON string):

```json
{
  "schema_version": 1,
  "phase": "s7.1",
  "installation_complete": true,
  "firstboot_provisioning": "pending",
  "source_media_version": "26.04.1",
  "source_commit": "<40-hex-char commit sha>"
}
```

Schema: `schemas/installer-install-state.schema.json`.

## What S7.1 must never do (Section 28)

```text
activate Focus
enable Tor globally
create cyber containers
install AI models
perform user desktop personalization
run full hardware optimization
```

`firstboot_provisioning` is **always** `"pending"` on an S7.1-produced
installation - `build_install_state_marker` has no parameter that could
ever set it to anything else, and the Installer Layer-B closure gate
(`serein.installer.closure.enforce_installer_layer_b_closure`)
explicitly requires `firstboot_provisioning == "pending"`, failing
closure if a future change accidentally marked it otherwise.

## Verification (Section 48)

The real Layer-B workflow reads this marker directly off the installed
target's root filesystem (`installer/scripts/inspect-target-layout.sh`
mounts the root partition read-only, checks for
`/etc/serein/install-state.json`, and reports both
`serein_core_present` and the real `firstboot_provisioning` value it
contains) rather than depending on interactive shell/SSH access inside
the booted guest, which this phase does not set up.

## What S7.2 will do with this

S7.2 ("First-boot provisioning" - `docs/distribution/s7-roadmap.md`)
will consume this marker to apply the desktop/hardware/dev/AI/cyber/
veil/focus profile resources S7.0 only *embeds* on media today into the
freshly-installed target system, flipping `firstboot_provisioning` to
`"complete"` once done. None of that logic exists in this repository
yet - S7.1 stops exactly at "installed, bootable, provisioning
pending."
