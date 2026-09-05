# Hardware Discovery Contract

## Goal

Produce a stable, schema-validated `HardwareReport` (see
`schemas/hardware-report.schema.json`) describing the host without root and
without ever raising an exception to the caller. Missing information is
represented as `null`/empty, never guessed and never fatal.

## Data sources, in order of preference

1. Kernel/system interfaces: `/etc/os-release`, `/proc/cpuinfo`,
   `/proc/meminfo`, `/proc/sys/kernel/*`, `/sys/class/drm`,
   `/sys/block`, `/sys/class/power_supply`, `/sys/class/dmi/id`.
2. Python's `platform`/`os` standard-library modules, used only as a
   fallback when probing the *real* host and the kernel interface above is
   unavailable (e.g. running the CLI on a non-Linux development machine).
   This fallback is intentionally never used against injected test fixture
   roots, so tests stay deterministic and host-independent.
3. External commands (e.g. `lspci`) — **not implemented in S0.** Reserved
   as an optional future enrichment for friendlier GPU/device names. The
   probe must keep working with a vendor-only GPU label if such a command
   is absent, which is exactly S0's current behavior.

## Documented assumptions

These are simplifications the probe makes today; each is a candidate for
refinement in a later phase, not a hidden bug:

- **GPU vendor → integrated/discrete** is a static mapping (Intel =
  integrated, AMD/NVIDIA = discrete). This misclassifies Intel discrete
  Arc GPUs and AMD APUs. Acceptable for S0 because nothing yet acts on
  `kind`; it is descriptive only.
- **Storage classification** uses the device name prefix (`nvme*`) and the
  `queue/rotational` flag rather than resolving the `device` symlink to a
  PCI/USB path. This is simpler, fixture-friendly (no symlinks required),
  and sufficient to distinguish NVMe/SSD/HDD, which is all S0 needs.
- **Virtualization detection** is heuristic (DMI strings, the `hypervisor`
  CPU flag, `/proc/version` for WSL, `/proc/1/cgroup`/`.dockerenv` for
  containers). It is informational for `status`/`doctor` output only and
  must never be treated as a security boundary check.
- **`/etc/os-release` format** follows the freedesktop.org os-release
  specification, stable across Ubuntu releases since 16.04.

## Invariants a hardware-probe change must preserve

- No probe function may raise for missing/unreadable files; `_util.read_text`
  /`read_int` swallow `OSError` by design.
- `probe_hardware()` wraps every sub-probe in an additional safety net
  (`_safely`) — a bug in one section degrades that section to its empty
  default rather than failing the whole report.
- A field added to `HardwareReport` must be added to
  `schemas/hardware-report.schema.json` and covered by a fixture-based
  test in the same change.
- GPUs may be zero, one, or many. Storage devices may be zero, one, or
  many. Batteries may be zero (desktop) or more than one. None of these
  counts may be assumed.

## What this contract explicitly excludes

Per the security model, the probe never collects hostname, MAC addresses,
IP addresses, disk/machine serial numbers, or usernames — there is nothing
in `HardwareReport` to redact before pasting `serein status`/`serein
hardware probe` output into a bug report.
