# S2R — ZRAM Validation (Defects A, B, C)

Environment: disposable `Ubuntu-26.04` WSL2 instance (see `README.md`).

## Package validation

```
$ apt-cache policy systemd-zram-generator
systemd-zram-generator:
  Installed: (none)
  Candidate: 1.2.1-2
  Version table:
     1.2.1-2 500
        500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages
```

Installed for real (`apt-get install -y systemd-zram-generator`, exit 0)
inside the disposable VM.

## Defect A/B: config syntax — real, installed `zram-generator.conf(5)`

Extracted directly from the real, installed man page
(`zcat /usr/share/man/man5/zram-generator.conf.5.gz`):

**Config search paths (exact SYNOPSIS):**
```
/usr/lib/systemd/zram-generator.conf
/usr/local/lib/systemd/zram-generator.conf
/etc/systemd/zram-generator.conf
/run/systemd/zram-generator.conf

/usr/lib/systemd/zram-generator.conf.d/*.conf
/usr/local/lib/systemd/zram-generator.conf.d/*.conf
/etc/systemd/zram-generator.conf.d/*.conf
/run/systemd/zram-generator.conf.d/*.conf
```
Precedence: the base `.conf` file is read first and has the *lowest*
precedence; `.conf.d/*.conf` snippets across all four conf.d directories
are merged and sorted lexicographically by filename, with the
lexicographically-latest name winning for single-value options.

**Current options (OPTIONS section):**
```
zram-size=              Defaults to min(ram / 2, 4096)
compression-algorithm=  If unset, none will be configured and the
                         kernel's default will be used.
swap-priority=          If unset, 100 is used.
```

**OBSOLETE OPTIONS section (verbatim):**
```
memory-limit=      Compatibility alias for host-memory-limit.
zram-fraction=     Defaulted to 0.5. Setting this or max-zram-size
                   overrides zram-size.
max-zram-size=     Defaulted to 4096. Setting this or zram-fraction
                   overrides zram-size.
```

This directly confirms all three S2R claims: `zram-fraction`/
`max-zram-size` are formally obsolete; `zram-size = min(ram / 2, 4096)`
is the real current default (same *value* S2 always intended, wrong
*option name*); `compression-algorithm` unset (not `zstd`) is the real
default.

## Real config-parse validation (not just documentation)

The full `generate` invocation (used at real boot) refuses to run under
WSL2's container-detected virtualization (see
`virtualization-validation.md`), so the lower-level `--setup-device`
path was used instead to validate the corrected syntax against the real
binary:

```
$ cat /etc/systemd/zram-generator.conf.d/90-serein.conf
[zram0]
zram-size = min(ram / 2, 4096)
swap-priority = 100

$ /usr/lib/systemd/system-generators/zram-generator --setup-device zram0
/dev/zram0 successfully formatted as swap (label "zram0", uuid ...)
$ echo $?
0

$ lsblk | grep zram
zram0 253:0    0   3.4G  0 disk
```

The resulting device size (~3.4 GiB, on a VM with ~7 GiB RAM) matches
`min(ram/2, 4096)` exactly (7 GiB / 2 ≈ 3.5 GiB, under the 4096 MiB
cap). The device was reset (`--reset-device zram0`) after this test —
nothing was left running in the disposable VM, which was itself
unregistered at the end of the session.

## Defect C: `zram_configurable` capability — real evidence

`/sys/class/zram-control` (the kernel's hot-add/hot-remove control
interface) was confirmed present in the WSL2 kernel (`hot_add`/
`hot_remove` entries), used as the new, real "kernel supports zram"
signal in `capabilities.py` in place of the old unconditional `True`.

## Defect: unit name used in `serein hardware plan`'s verification field

Confirmed via `strings` on the real installed generator binary that it
creates `systemd-zram-setup@<device>.service` (instantiated as
`systemd-zram-setup@zram0.service`) and a `dev-<device>.swap` unit —
matching what `planner.py`'s `memory.zram` action already referenced in
its `verification` field. No change needed there.

## Target ownership (`/etc/systemd/zram-generator.conf.d/90-serein.conf`)

```
$ dpkg-query -S /etc/systemd/zram-generator.conf.d/90-serein.conf
dpkg-query: no path found matching pattern ...
$ dpkg-query -S /etc/systemd/zram-generator.conf.d
dpkg-query: no path found matching pattern ...
$ dpkg-query -S /etc/systemd/zram-generator.conf
dpkg-query: no path found matching pattern ...
```

Archive-wide `apt-file search zram-generator.conf.d` returned only
`librust-zram-generator-dev`'s own bundled Cargo test fixtures under
`/usr/share/cargo/registry/...` — the upstream project's own unit
tests, not real runtime config paths, and not the target path. **Confirmed
unowned, both before and after considering the full archive.**

## Verdict

```
S2R_ZRAM_PACKAGE_VALIDATED=true
S2R_ZRAM_CONFIG_PARSE_VALIDATED=true   (via --setup-device; full `generate` path BLOCKED under WSL - see known-blockers.md)
S2R_ZRAM_TARGET_OWNERSHIP_VALIDATED=true
```

## S2RM addendum — capability/planner consistency

A follow-up review (S2RM) found that, independent of the corrections
above, `serein hardware capabilities` and `serein hardware plan` could
disagree about the same machine: capabilities could report
`zram_configurable = false` while the planner still returned
`memory.zram = APPLY`, since each independently derived its own answer
from the same underlying evidence. Fixed by extracting one shared
function, `memory_policy.detect_zram_capability()`, that both now call
— see `docs/hardware/memory-policy.md`'s "Capability-gated planning"
section for the corrected decision order and
`tests/test_hardware_policy.py::TestZramCapabilityPlannerInvariant` for
the regression coverage (checked across every fixture scenario and all
five profiles). This was a code-consistency defect, not a new upstream
fact requiring live validation — no additional live evidence was needed
beyond what `detect_zram_capability`'s existing logic already used.
